"""Resideo evohomesecurity API library"""

import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
from .const import VERSION, BASE_URL, NAME, RETRY_DELAY, RETRY_LIMIT, SESSION_RESET_DELAY
from .dataclass import Event
from .enum import PanelState
from .exception import ApiException, AuthException, CmdException, ParseException


_LOGGER = logging.getLogger(__name__)


class EvohomeSecurityApiClient:
    """Client for evohomesecurity API"""

    def __init__(self, email: str, password: str, session: Optional[aiohttp.ClientSession] = None) -> None:
        """Initialise evohomesecurity API client"""
        if email is None or password is None:
            raise AuthException("Credentials not provided")
        
        # Credentials
        self.email: str = email
        self._password: str = password
        
        # Session
        self._session: aiohttp.ClientSession = session
        self._session_timeout: int | None = 180
        
        # Token
        self._token: str | None = None
        self._token_creation: datetime | None = None
        self._token_expiry: datetime | None = None
        
        # Panel
        self._panel_serial: str | None = None
        self._panel_state: PanelState = PanelState.UNKNOWN

        # Services
        self._services: list | None = None

        # Events
        self._events: Dict | None = None

    # Authentication

    async def async_login(self) -> bool:
        """Login using credentials and obtain a token"""
        if self._session is None:
            self._session = aiohttp.ClientSession()
            
        async with (asyncio.timeout(self._session_timeout)):
            url = f"{BASE_URL}/security/authenticate"
            auth = aiohttp.BasicAuth(self.email, self._password + ':1:3')  # TODO: Determine if salt is dynamic
            async with self._session.post(url=url, headers=self._headers, auth=auth) as resp:

                # Check HTTP status code
                if resp.status != 200:
                    raise AuthException(f"Failed to authenticate: HTTP {resp.status} {resp.reason}")
                
                # Check API status code
                data = await resp.json()
                if data['code'] != 0:
                    raise AuthException(f"Failed to authenticate: API {data['code']} {data['message']}")
                
                # Session
                self._session_timeout = data['sessionTimeout']
                
                # Token
                self._token = data['sessionToken']
                self._token_creation = datetime.now()
                self._update_token_expiry()
                
                # Panel
                self._panel_serial = data['panel']['account']['identificationCode']

                return True

    async def async_logout(self) -> bool:
        """Logout and destroy token"""
        if not self.token_valid:
            return True

        if self._session is None:
            self._session = aiohttp.ClientSession()

        async with asyncio.timeout(self._session_timeout):
            url = f"{BASE_URL}/security/logout"
            async with self._session.post(url=url, headers=self._headers) as resp:

                # Check HTTP status code
                if resp.status != 200:
                    raise AuthException(f"Failed to logout: HTTP {resp.status} {resp.reason}")

                # Check API status code
                data = await resp.json()
                if data['code'] != 1:
                    raise AuthException(f"Failed to authenticate: API {data['code']} {data['message']}")

                # Clear token
                self._token = None
                self._token_creation = None
                self._token_expiry = None

        return True

    # Panel state

    async def async_set_full_arm(self) -> bool:
        """Push request for full arm"""
        return await self._async_set_state(cmd='arm', verify_state=PanelState.FULL_ARM)

    async def async_set_partial_arm(self) -> bool:
        """Push request for partial arm"""
        return await self._async_set_state(cmd='partialArm', verify_state=PanelState.PARTIAL_ARM)

    async def async_set_disarm(self) -> bool:
        """Push request for disarm"""
        return await self._async_set_state(cmd='disarm', verify_state=PanelState.DISARM)

    async def async_get_state(self) -> bool:
        """Get panel state"""
        event_id = await self._async_get_event_id()
        self._panel_state = PanelState(
            await self._async_api_request(
                url=f"/panel/commands/status/{event_id:.0f}/status?isBusy=true",
                type='get',
                parser=lambda x: x['errorCode'] if x['statusCode'] == 2 else 0
            )
        )
        return True

    # Services

    async def async_get_services(self) -> bool:
        """Get services"""
        await self._async_auto_refresh()
        async with asyncio.timeout(self._session_timeout):
            url = f"{BASE_URL}/services"
            async with self._session.get(url=url, headers=self._headers) as resp:

                # Check HTTP status code
                if resp.status != 200:
                    raise ApiException(f"Failed to retrieve services: HTTP {resp.status} {resp.reason}")

                # Try parsing response
                data = await resp.json()
                if 'service' not in data or len(data['service']) == 0:
                    raise ApiException("Failed to retrieve services")
                self._services = data['service']
        self._update_token_expiry()
        return True

    # Event log

    async def async_get_events(self, num_events:int=20) -> bool:
        """Get events"""
        eventlog_id = await self._async_api_request(
            url="/panel/commands/eventlog",
            type="put",
            parser=lambda x: x['id'] if x['status'] == 'success' else None
        )

        await self._async_api_request(
            url=f"/panel/commands/eventlog/{eventlog_id:.0f}/status?isBusy=true",
            type="get",
            parser=lambda x: x['id'] if x['messageKey'] == 'evohomesecurity.eventlog.ok' else None
        )

        eventlog = await self._async_api_request(
            url=f"/panel/logs?startIndex=0&lines={num_events:.0f}&filter=home.events.filter.all",
            type="get",
            parser=lambda x: sorted([Event(
                    id=e['logId'],
                    message=e['logMessage'],
                    timestamp=datetime.strptime(e['logTime'], '%Y-%m-%d %H:%M:%S'),
                    picture_id=e['pictureLinkId']
                ) for e in x['logDataList']],
                key=lambda y: y.timestamp,
                reverse=True
            )
        )
        self._events = eventlog
        return True

    # Internal methods

    def _update_token_expiry(self) -> None:
        """Update token expiry, including a small buffer for delays"""
        self._token_expiry = datetime.now() + timedelta(seconds=self._session_timeout) - timedelta(seconds=RETRY_DELAY)

    async def _async_auto_refresh(self) -> bool:
        """Refresh token if required"""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        if not self.token_valid:
            await self.async_logout()
            await asyncio.sleep(SESSION_RESET_DELAY)
            await self.async_login()
        return True

    async def _async_api_request(
            self,
            url:str,
            type:str,
            payload:Optional[Dict]=None,
            parser:Optional[Callable[[Dict], Any]]=None
    ) -> Any:
        """Put command"""
        parsed_data = None
        await self._async_auto_refresh()
        async with asyncio.timeout(self._session_timeout):
            url = f"{BASE_URL}{url}"
            for attempt in range(1, RETRY_LIMIT + 1):
                try:
                    # Send correct request type
                    if type == 'put':
                        req = self._session.put
                    elif type == 'post':
                        req = self._session.post
                    elif type == 'get':
                        req = self._session.get
                    else:
                        raise NotImplementedError(f"Request {type} not implemented")

                    async with req(url=url, headers=self._headers, json=payload) as resp:

                        # Check HTTP status code
                        if resp.status != 200:
                            raise CmdException(
                                f"Command {url} failed after {attempt} tries: HTTP {resp.status} {resp.reason}")

                        # Parse response
                        if not parser:
                            break
                        raw_data = await resp.json()
                        parsed_data = parser(raw_data)
                        if parsed_data:
                            break
                        else:
                            raise ParseException(f"Failed to parse response: {raw_data}")

                except (CmdException, ParseException):
                    if attempt < RETRY_LIMIT:
                        await asyncio.sleep(RETRY_DELAY)
                    else:
                        raise

        self._update_token_expiry()
        return parsed_data

    async def _async_set_state(self, cmd:str, verify_state:Optional[PanelState]=None) -> bool:
        """Set panel state"""
        ret_val = await self._async_api_request(
            url=f"/panel/commands/{cmd}?isBusy=true",
            type='put',
            payload={'key': '', 'value': ''},
            parser=lambda x: x['status'] == "success")
        if verify_state:
            await self.async_get_state()
            ret_val = self.panel_state == verify_state
        return ret_val

    async def _async_get_event_id(self) -> int:
        """Get an event ID"""
        return await self._async_api_request(
            url='/panel/commands/status?isBusy=true',
            type='put',
            payload={'key': 'serial', 'value': self._panel_serial},
            parser=lambda x: x['id'] if x['status'] == "success" else None
        )

    # Properties

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Connection': 'keep-alive',
            'Host': 'tc20e.total-connect.eu',
            'Accept-Encoding': 'gzip, deflate',
            'User-Agent': f'{NAME}/{VERSION}'
        }
        if self._token:
            headers['x-session-token'] = self._token
        return headers

    @property
    def token_valid(self) -> bool:
        if self._token is None:
            return False
        elif self._token_expiry and self._token_expiry < datetime.now():
            return False
        return True

    @property
    def panel_serial(self) -> str:
        return self._panel_serial

    @property
    def panel_state(self) -> PanelState:
        return self._panel_state

    @property
    def services(self) -> list[str]:
        return self._services

    @property
    def events(self) -> Dict:
        return self._events
