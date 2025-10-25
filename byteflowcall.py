import os
import requests
from dotenv import load_dotenv
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import logging

# Load environment variables from .env file
load_dotenv()

# --- Configuration and Initialization ---
BYTEFLOW_API_KEY = os.getenv("BYTEFLOW_API_KEY")
# For testing purposes, if the key is not set, we'll use a dummy one
# This will be overridden by fixtures in tests.
if not BYTEFLOW_API_KEY:
    os.environ["BYTEFLOW_API_KEY"] = "dummy_key_for_tests"
    BYTEFLOW_API_KEY = "dummy_key_for_tests"


BASE_URL = os.getenv("BYTEFLOW_API_BASE_URL", "https://apidoc.byteflow.bot")

HEADERS = {
    "Content-Type": "application/json"
}

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Custom Exception for Byteflow API Errors ---
class ByteflowAPIError(Exception):
    """Custom exception for Byteflow API errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_text = response_text

# --- Internal API Client Helper ---
def _make_request(method: str, endpoint: str, params: Optional[Dict[str, Any]] = None, json_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Internal helper to make HTTP requests to the Byteflow Bot API.

    Args:
        method: The HTTP method (e.g., "GET", "POST").
        endpoint: The API endpoint path (e.g., "/api/health").
        params: Dictionary of query parameters.
        json_data: Dictionary of JSON data for the request body.

    Returns:
        The JSON response from the API.

    Raises:
        ByteflowAPIError: If an error occurs during the API request.
    """
    url = f"{BASE_URL}{endpoint}"
    try:
        # Update headers with the current BYTEFLOW_API_KEY in case it was set after initial load
        current_headers = HEADERS.copy()
        bearer_token = os.getenv("BYTEFLOW_API_KEY", "dummy_key_for_tests")
        # Support both Bearer and X-API-Key header styles
        current_headers["Authorization"] = f"Bearer {bearer_token}"
        current_headers["X-API-Key"] = bearer_token

        response = requests.request(method, url, headers=current_headers, params=params, json=json_data, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        error_message = f"Byteflow API HTTP Error: {e.response.status_code} - {e.response.text}"
        logger.error(f"API Request failed: {method} {url} - {error_message}")
        raise ByteflowAPIError(error_message, e.response.status_code, e.response.text) from e
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Byteflow API Connection Error: {e}")
        raise ByteflowAPIError(f"Byteflow API Connection Error: {e}") from e
    except requests.exceptions.Timeout as e:
        logger.error(f"Byteflow API Timeout Error: {e}")
        raise ByteflowAPIError(f"Byteflow API Timeout Error: {e}") from e
    except requests.exceptions.RequestException as e:
        logger.error(f"An unexpected request error occurred with Byteflow API: {e}")
        raise ByteflowAPIError(f"An unexpected request error occurred with Byteflow API: {e}") from e
    except Exception as e:
        logger.exception(f"An unexpected error occurred during API request to {url}")
        raise ByteflowAPIError(f"An unexpected error occurred during API request: {e}") from e

# --- Pydantic Models for Tool Inputs ---
class CallIdInput(BaseModel):
    """
    Input model for tools requiring a call ID.
    """
    call_id: str = Field(..., description="The unique identifier of the call.")

class StartCallInput(BaseModel):
    """
    Input model for starting a new call.
    Backwards compatible fields (to_number/from_number) are mapped to API spec fields
    (destination/did_number/ai_client).
    """
    # Backward-compatible inputs
    to_number: Optional[str] = Field(None, description="Recipient phone 0. Will map to destination if provided.")
    from_number: Optional[str] = Field(None, description="DID to use. Will map to did_number if provided.")

    # API spec fields (preferred)
    destination: Optional[str] = Field(None, description="Phone number to call 0)")
    did_number: Optional[str] = Field(None, description="DID number to use (e.g., 08069256212)")
    ai_client: Optional[str] = Field(None, description="AI client type: client1 | client2 | client3")

    # Optional extras kept for possible future use
    script_id: Optional[str] = Field(None, description="The ID of the script/template to use for the call.")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata to associate with the call (key-value pairs).")

    system_prompt: str = Field(..., description="The System prompt to guide the AI during the call.")
    greeting_text: str = Field(..., description="The greeting message to be played at the start of the call.")


# --- FastMCP Server Initialization ---
mcp = FastMCP("byteflow-call-manager", version="1.0.0")

# --- MCP Tools ---

@mcp.tool()
def get_health_status() -> Dict[str, Any] | str:
    """
    Checks the health and operational status of the Byteflow Bot API.
    This tool can be used to verify if the Byteflow Bot service is online and responsive.

    Returns:
        A dictionary containing the health status (e.g., {"status": "healthy", "timestamp": "..."})
        or a string with an error message if the request fails.
    """
    try:
        response = _make_request("GET", "/api/health")
        return response
    except ByteflowAPIError as e:
        logger.error(f"Error in get_health_status: {e.message}")
        return f"Failed to get health status: {e.message}"
    except Exception as e:
        logger.exception("An unexpected error occurred in get_health_status")
        return f"An unexpected error occurred: {e}"

@mcp.tool()
def get_configuration() -> Dict[str, Any] | str:
    """
    Retrieves the current configuration settings of the Byteflow Bot system.
    This can include various operational parameters and feature flags.

    Returns:
        A dictionary containing the configuration settings (e.g., {"max_calls": 100, "default_did": "+15551234567"})
        or a string with an error message if the request fails.
    """
    try:
        response = _make_request("GET", "/api/config")
        return response
    except ByteflowAPIError as e:
        logger.error(f"Error in get_configuration: {e.message}")
        return f"Failed to get configuration: {e.message}"
    except Exception as e:
        logger.exception("An unexpected error occurred in get_configuration")
        return f"An unexpected error occurred: {e}"

@mcp.tool()
def get_call_status(input: CallIdInput) -> Dict[str, Any] | str:
    """
    Retrieves the current status and detailed information of a specific call.
    This includes call duration, start/end times, numbers involved, and associated metadata.

    Args:
        input: An object containing the `call_id` (string) of the call to retrieve status for.

    Returns:
        A dictionary with call details (e.g., {"call_id": "...", "status": "in-progress", "duration": 120})
        or a string with an error message if the call is not found or the request fails.
    """
    try:
        response = _make_request("GET", f"/api/call/{input.call_id}")
        return response
    except ByteflowAPIError as e:
        logger.error(f"Error in get_call_status for call_id {input.call_id}: {e.message}")
        if e.status_code == 404:
            return f"Call with ID '{input.call_id}' not found. Please check the call ID."
        return f"Failed to get call status for '{input.call_id}': {e.message}"
    except Exception as e:
        logger.exception(f"An unexpected error occurred in get_call_status for call_id {input.call_id}")
        return f"An unexpected error occurred: {e}"

@mcp.tool()
def get_call_transcript(input: CallIdInput) -> Dict[str, Any] | str:
    """
    Fetches the transcript of a completed or in-progress call.
    The transcript includes speaker, text, and timestamp for each segment.

    Args:
        input: An object containing the `call_id` (string) of the call to retrieve the transcript for.

    Returns:
        A dictionary containing the call ID and a list of transcript entries
        (e.g., {"call_id": "...", "transcript": [{"speaker": "agent", "text": "Hello"}]})
        or a string with an error message if the transcript is not available or the request fails.
    """
    try:
        response = _make_request("GET", f"/api/call/{input.call_id}/transcript")
        return response
    except ByteflowAPIError as e:
        logger.error(f"Error in get_call_transcript for call_id {input.call_id}: {e.message}")
        if e.status_code == 404:
            return f"Transcript for call ID '{input.call_id}' not found or call does not exist. It might not be available yet."
        return f"Failed to get call transcript for '{input.call_id}': {e.message}"
    except Exception as e:
        logger.exception(f"An unexpected error occurred in get_call_transcript for call_id {input.call_id}")
        return f"An unexpected error occurred: {e}"

@mcp.tool()
def get_active_calls() -> List[Dict[str, Any]] | str:
    """
    Lists all currently active calls managed by the Byteflow Bot system.
    This provides an overview of ongoing conversations.

    Returns:
        A list of dictionaries, each representing an active call's status
        (e.g., [{"call_id": "...", "status": "in-progress"}, ...])
        or a string with an error message if the request fails.
    """
    try:
        response = _make_request("GET", "/api/calls/active")
        return response
    except ByteflowAPIError as e:
        logger.error(f"Error in get_active_calls: {e.message}")
        return f"Failed to get active calls: {e.message}"
    except Exception as e:
        logger.exception("An unexpected error occurred in get_active_calls")
        return f"An unexpected error occurred: {e}"

@mcp.tool()
def list_available_dids() -> List[Dict[str, Any]] | Dict[str, Any] | str:
    """
    Retrieves a list of available DIDs (Direct Inward Dialing numbers) that can be used for making calls.
    These numbers can be used as the `from_number` when initiating new calls.

    Returns:
        A list of strings, each representing an available DID (e.g., ["+15551112222", "+15553334444"])
        or a string with an error message if the request fails.
    """
    try:
        # Primary: explicit validation + fetch (works across environments)
        response = _make_request("POST", "/api/validate-and-fetch-dids")
        return response
    except ByteflowAPIError as e_primary:
        logger.error(f"Primary DID fetch failed (/api/validate-and-fetch-dids): {e_primary.message}")
        # Fallback 1: user-owned DIDs
        try:
            fallback1 = _make_request("GET", "/api/did/my-dids")
            return fallback1
        except ByteflowAPIError as e_fb1:
            logger.error(f"Fallback DID fetch failed (/api/did/my-dids): {e_fb1.message}")
            # Fallback 2: generic list
            try:
                fallback2 = _make_request("GET", "/api/dids")
                return fallback2
            except ByteflowAPIError as e_fb2:
                logger.error(f"Error in list_available_dids: {e_fb2.message}")
                return f"Failed to list available DIDs: {e_fb2.message}"
    except Exception as e:
        logger.exception("An unexpected error occurred in list_available_dids")
        return f"An unexpected error occurred: {e}"

@mcp.tool()
def start_new_call(input: StartCallInput) -> Dict[str, Any] | str:
    """
    Initiates a new outbound call to a specified recipient.
    The `to_number` is required. Optional parameters include `from_number` (a DID),
    `script_id` for automated call flows, and `metadata` for custom information.

    Args:
        input: An object containing call initiation parameters:
            - `to_number` (string, required): The recipient's phone number (E.164 format) Make sure local calls start with 0, Example 08069256212.
            - `from_number` (string, optional): The DID to use for making the call.
            - `script_id` (string, optional): The ID of the script to use for the call.
            - `system_prompt` (string, required): The System prompt to guide the AI during the call.
            - `greeting_text` (string, required): The greeting message to be played at the start of the call.
            - `metadata` (dict, optional): Additional key-value metadata for the call.

    Returns:
        A dictionary with the new call's ID and initial status (e.g., {"call_id": "...", "status": "initiated"})
        or a string with an error message if the call cannot be started.
    """
    try:
        # Map inputs to API spec
        destination = input.destination or input.to_number
        did_number = input.did_number or input.from_number
        ai_client = input.ai_client or "client1"
        system_prompt = input.system_prompt or "You are an AI assistant helping with a phone call."
        greeting_text = input.greeting_text or "Hello! This is an automated call."

        if not destination:
            return "Failed to start call due to invalid input: destination/to_number is required."

        if not did_number:
            # Attempt to auto-select a DID
            try:
                did_resp = _make_request("POST", "/api/validate-and-fetch-dids")
                dids = []
                if isinstance(did_resp, dict) and "dids" in did_resp and isinstance(did_resp["dids"], list):
                    dids = did_resp["dids"]
                if dids:
                    first_did = dids[0]
                    # Response may be objects with did_number or strings
                    did_number = first_did.get("did_number") if isinstance(first_did, dict) else str(first_did)
            except Exception:
                pass

        if not did_number:
            return "Failed to start call: did_number/from_number is required (no default DID available)."

        payload: Dict[str, Any] = {
            "destination": destination,
            "did_number": did_number,
            "ai_client": ai_client,
            "system_prompt": system_prompt,
            "greeting_text": greeting_text
        }

        # Optional passthroughs if provided
        if input.script_id is not None:
            payload["script_id"] = input.script_id
        if input.metadata is not None:
            payload["metadata"] = input.metadata

        response = _make_request("POST", "/api/call", json_data=payload)
        return response
    except ByteflowAPIError as e:
        logger.error(f"Error in start_new_call to {input.to_number}: {e.message}")
        if e.status_code == 400 or e.status_code == 422:
            return f"Failed to start call due to invalid input: {e.response_text}. Please check the provided numbers and parameters."
        return f"Failed to start call to '{input.to_number}': {e.message}"
    except Exception as e:
        logger.exception(f"An unexpected error occurred in start_new_call to {input.to_number}")
        return f"An unexpected error occurred: {e}"

@mcp.tool()
def force_disconnect_call(input: CallIdInput) -> Dict[str, Any] | str:
    """
    Forces the immediate disconnection of an active call.
    This action cannot be undone and will terminate the call regardless of its current state.

    Args:
        input: An object containing the `call_id` (string) of the call to disconnect.

    Returns:
        A dictionary with the call's ID and its new status (e.g., {"call_id": "...", "status": "disconnected"})
        or a string with an error message if the call is not found or cannot be disconnected.
    """
    try:
        response = _make_request("POST", f"/api/call/{input.call_id}/force-disconnect")
        return response
    except ByteflowAPIError as e:
        logger.error(f"Error in force_disconnect_call for call_id {input.call_id}: {e.message}")
        if e.status_code == 404:
            return f"Call with ID '{input.call_id}' not found or already disconnected. Cannot force disconnect."
        return f"Failed to force disconnect call '{input.call_id}': {e.message}"
    except Exception as e:
        logger.exception(f"An unexpected error occurred in force_disconnect_call for call_id {input.call_id}")
        return f"An unexpected error occurred: {e}"

# --- Main Execution Block ---
if __name__ == "__main__":
    port = int(os.getenv("MCP_SERVER_PORT", 8000))
    logger.info(f"Starting Byteflow MCP Server on port {port}")

    # Deploy with HTTP transport
    mcp.run(transport='http', host='0.0.0.0', port=8002, path='/mcp')

    # mcp.run(transport='stdio')