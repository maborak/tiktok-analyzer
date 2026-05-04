
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from api_main import app
from config import settings
from domain.entities.queue_schemas import QueueTaskResponse, QueueSubmissionRequest, CheckResultData

client = TestClient(app)

# Mock data
MOCK_QUEUE_KEY = "test_queue_key"
MOCK_WORKER_ID = 1001
MOCK_ASIN = "B07ZPKN6BW"

@pytest.fixture
def mock_settings():
    with patch("config.settings") as mock_settings:
        def side_effect(key, default=None):
            if key == "QUEUE_KEY":
                return MOCK_QUEUE_KEY
            if key == "API_QUEUE_LIMIT_DEFAULT":
                return 1
            if key == "API_QUEUE_LIMIT_MAX":
                return 50
            if key == "SCREENSHOT_SERVICE_URL":
                return "http://screenshot-service:3000/amazon/"
            return default
        mock_settings.side_effect = side_effect
        yield mock_settings

@pytest.fixture
def mock_persistence():
    with patch("routes.queue.data_persistence_adapter") as mock_db:
        yield mock_db

@pytest.fixture
def mock_product_service():
    with patch("routes.queue.product_service") as mock_service:
        yield mock_service

@pytest.fixture
def mock_monitoring_service():
    with patch("routes.queue.monitoring_service") as mock_service:
        yield mock_service

@pytest.fixture
def mock_cookie_config():
    with patch("utils.cookie_config.get_cookie_config") as mock_config_getter:
        mock_config = MagicMock()
        mock_config.get_country_cookies.return_value = "session-id=123"
        mock_config.get_all_countries.return_value = {"US": "session-id=123", "UK": "session-id=456"}
        mock_config_getter.return_value = mock_config
        yield mock_config

def test_get_queue_unauthorized(mock_settings):
    response = client.get("/queue", headers={"X-Queue-Key": "wrong_key"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Queue Key"

def test_get_queue_no_tasks(mock_settings, mock_persistence, mock_monitoring_service):
    mock_persistence.acquire_product_locks_batch.return_value = []
    mock_persistence.get_scraper_config.return_value = {"headers": {"User-Agent": "test"}}
    
    response = client.get("/queue", headers={"X-Queue-Key": MOCK_QUEUE_KEY})
    assert response.status_code == 204

def test_get_queue_success(mock_settings, mock_persistence, mock_cookie_config, mock_monitoring_service):
    mock_persistence.acquire_product_locks_batch.return_value = [MOCK_ASIN]
    mock_persistence.get_scraper_config.return_value = {"headers": {"User-Agent": "test"}}
    
    response = client.get("/queue", headers={"X-Queue-Key": MOCK_QUEUE_KEY})
    
    assert response.status_code == 200
    data = response.json()
    assert data["worker_id"] == 1000 # Default worker ID
    assert data["tasks"][0]["asin"] == MOCK_ASIN
    assert "US" in data["countries"]
    assert data["screenshot_service_url"] == "http://screenshot-service:3000/amazon/"

def test_get_queue_with_params(mock_settings, mock_persistence, mock_cookie_config, mock_monitoring_service):
    mock_persistence.acquire_product_locks_batch.return_value = [MOCK_ASIN]
    mock_persistence.get_scraper_config.return_value = {"headers": {"User-Agent": "test"}}
    
    params = {
        "limit": 5,
        "country": "US",
        "worker_id": MOCK_WORKER_ID
    }
    
    response = client.get("/queue", headers={"X-Queue-Key": MOCK_QUEUE_KEY}, params=params)
    
    assert response.status_code == 200
    data = response.json()
    assert data["worker_id"] == MOCK_WORKER_ID
    assert len(data["countries"]) == 1
    assert "US" in data["countries"]
    
    mock_persistence.acquire_product_locks_batch.assert_called_with(
        limit=5,
        worker_id=MOCK_WORKER_ID,
        strategy="balanced",
        check_bias=300, # Default bias
        asins=None
    )

def test_submit_result_unauthorized(mock_settings):
    response = client.post("/queue/submit", headers={"X-Queue-Key": "wrong_key"}, json={})
    assert response.status_code == 401

def test_submit_result_success(mock_settings, mock_product_service):
    mock_product_service.process_remote_submission.return_value = {"success": True}
    
    payload = {
        "worker_id": MOCK_WORKER_ID,
        "asin": MOCK_ASIN,
        "country": "US",
        "check_result": {
            "success": True,
            "title": "Test Product",
            "price": "10.99",
            "currency": "$",
            "availability": "In Stock",
            "execution_time_ms": 100
        }
    }
    
    response = client.post("/queue/submit", headers={"X-Queue-Key": MOCK_QUEUE_KEY}, json=payload)
    
    assert response.status_code == 200
    assert response.json()["success"] is True
    mock_product_service.process_remote_submission.assert_called_once()

def test_submit_result_failure(mock_settings, mock_product_service):
    mock_product_service.process_remote_submission.return_value = {"success": False, "error": "Processing failed"}
    
    payload = {
        "worker_id": MOCK_WORKER_ID,
        "asin": MOCK_ASIN,
        "country": "US",
        "check_result": {
            "success": False
        }
    }
    
    response = client.post("/queue/submit", headers={"X-Queue-Key": MOCK_QUEUE_KEY}, json=payload)
    
    assert response.status_code == 400
    assert response.json()["detail"] == "Processing failed"
