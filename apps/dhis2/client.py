"""
DHIS2 API client for pushing aggregate data value sets.
"""

import base64
import logging
import requests
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class Dhis2Client:
    """Thin wrapper around the DHIS2 REST API for data value set push/pull."""

    def __init__(self, server_url: str, username: str = '', password: str = '',
                 api_token: str = '', timeout: int = 30):
        self.server_url = server_url.rstrip('/')
        self.username = username
        self.password = password
        self.api_token = api_token
        self.timeout = timeout

    @classmethod
    def from_config(cls, config):
        """Build a client from a Dhis2Config model instance."""
        return cls(
            server_url=config.server_url,
            username=config.username,
            password=config.password,
            api_token=config.api_token or '',
        )

    def _headers(self) -> Dict[str, str]:
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if self.api_token:
            headers['Authorization'] = f'ApiToken {self.api_token}'
        elif self.username and self.password:
            credentials = f'{self.username}:{self.password}'
            encoded = base64.b64encode(credentials.encode()).decode()
            headers['Authorization'] = f'Basic {encoded}'
        return headers

    def _url(self, path: str) -> str:
        return f'{self.server_url}/api/{path.lstrip("/")}'

    def push_data_value_set(self, data_values: List[Dict], data_set: str,
                            org_unit: str, period: str) -> Dict:
        """POST a dataValueSet to DHIS2.

        Args:
            data_values: list of dicts with keys dataElement, value, and optionally categoryOptionCombo.
            data_set: DHIS2 data set UID.
            org_unit: DHIS2 organization unit UID.
            period: DHIS2 period code (e.g. '202608').

        Returns:
            Parsed JSON response from DHIS2.
        """
        payload = {
            'dataSet': data_set,
            'orgUnit': org_unit,
            'period': period,
            'dataValues': data_values,
        }

        url = self._url('dataValueSets')
        logger.info('Pushing %d data values to DHIS2 (orgUnit=%s, period=%s)',
                     len(data_values), org_unit, period)

        try:
            resp = requests.post(
                url, json=payload, headers=self._headers(), timeout=self.timeout
            )
            resp.raise_for_status()
            result = resp.json()
            logger.info('DHIS2 push succeeded: %s', result.get('description', 'OK'))
            return result
        except requests.exceptions.HTTPError as e:
            error_body = ''
            try:
                error_body = e.response.json()
            except Exception:
                error_body = e.response.text if e.response else ''
            logger.error('DHIS2 push failed (HTTP %s): %s', e.response.status_code, error_body)
            raise Dhis2PushError(f'HTTP {e.response.status_code}: {error_body}', response=error_body)
        except requests.exceptions.RequestException as e:
            logger.error('DHIS2 push failed (connection): %s', e)
            raise Dhis2PushError(str(e))

    def test_connection(self) -> Dict:
        """Ping the DHIS2 server to verify credentials."""
        url = self._url('me')
        try:
            resp = requests.get(url, headers=self._headers(), timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            raise Dhis2PushError(f'Connection test failed: {e}')

    def get_data_sets(self, query: str = '') -> List[Dict]:
        """Search for data sets by name."""
        url = self._url('dataSets')
        params = {'fields': 'id,name,periodType', 'paging': 'false'}
        if query:
            params['filter'] = f'name:ilike:{query}'
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get('dataSets', [])
        except requests.exceptions.RequestException as e:
            raise Dhis2PushError(f'Failed to fetch data sets: {e}')

    def get_org_units(self, query: str = '') -> List[Dict]:
        """Search for organization units by name."""
        url = self._url('organisationUnits')
        params = {'fields': 'id,name,level,path', 'paging': 'false'}
        if query:
            params['filter'] = f'name:ilike:{query}'
        try:
            resp = requests.get(url, headers=self._headers(), params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get('organisationUnits', [])
        except requests.exceptions.RequestException as e:
            raise Dhis2PushError(f'Failed to fetch org units: {e}')


class Dhis2PushError(Exception):
    """Raised when a DHIS2 API call fails."""

    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response
