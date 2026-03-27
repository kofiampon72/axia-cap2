import pytest
import os
import sys

# Ensure the project root is on the path so imports resolve correctly
_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _root)

# Set dummy environment variables BEFORE importing app/config,
# so config.py reads from os.environ instead of hardcoded values.
os.environ.setdefault("DB_HOST", "test-host")
os.environ.setdefault("DB_USER", "test-user")
os.environ.setdefault("DB_PASSWORD", "test-password")
os.environ.setdefault("DB_NAME", "test-db")
os.environ.setdefault("ENVIRONMENT", "testing")

from app import app  # noqa: E402
from utils import calculate_internal_metric  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Create a Flask test client with testing mode enabled."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


# ---------------------------------------------------------------------------
# Test 1 - Home route returns HTTP 200
# ---------------------------------------------------------------------------

def test_home_route_returns_200(client):
    """GET / should respond with a 200 OK status code."""
    response = client.get("/")
    assert response.status_code == 200, (
        f"Expected 200 but got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 2 - Home route returns valid JSON
# ---------------------------------------------------------------------------

def test_home_route_returns_valid_json(client):
    """GET / should return a valid JSON body."""
    response = client.get("/")
    assert response.content_type == "application/json", (
        f"Expected application/json but got {response.content_type}"
    )
    data = response.get_json()
    assert data is not None, (
        "Response body could not be parsed as JSON"
    )
    assert "message" in data, (
        "Expected a 'message' key in the JSON response"
    )


# ---------------------------------------------------------------------------
# Test 3 - Home route does NOT leak db_host
# ---------------------------------------------------------------------------

def test_home_route_does_not_leak_db_host(client):
    """GET / must not expose db_host in the response."""
    response = client.get("/")
    data = response.get_json()
    assert "db_host" not in data, (
        "SECURITY: 'db_host' is exposed in the home route response. "
        "Remove it from app.py."
    )


# ---------------------------------------------------------------------------
# Test 4 - Users route returns HTTP 200
# ---------------------------------------------------------------------------

def test_users_route_returns_200(client):
    """GET /users should respond with a 200 OK status code."""
    response = client.get("/users")
    assert response.status_code == 200, (
        f"Expected 200 but got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 5 - Users route returns valid JSON list
# ---------------------------------------------------------------------------

def test_users_route_returns_valid_json(client):
    """GET /users should return a valid JSON array."""
    response = client.get("/users")
    data = response.get_json()
    assert data is not None, (
        "Response body could not be parsed as JSON"
    )
    assert isinstance(data, list), (
        f"Expected a list but got {type(data).__name__}"
    )
    assert len(data) > 0, (
        "Expected at least one user in the response"
    )


# ---------------------------------------------------------------------------
# Test 6 - Users route does NOT leak db_password
# ---------------------------------------------------------------------------

def test_users_route_does_not_leak_db_password(client):
    """GET /users must not expose credentials in any user object."""
    response = client.get("/users")
    data = response.get_json()
    for user in data:
        assert "db_password" not in user, (
            "SECURITY: 'db_password' is exposed in /users. "
            "Remove it from database.py."
        )
        assert "db_user" not in user, (
            "SECURITY: 'db_user' is exposed in /users. "
            "Remove it from database.py."
        )


# ---------------------------------------------------------------------------
# Test 7 - calculate_internal_metric returns correct result
# ---------------------------------------------------------------------------

def test_calculate_internal_metric_correct_result():
    """calculate_internal_metric(a, b) should return a / b."""
    assert calculate_internal_metric(10, 2) == 5.0
    assert calculate_internal_metric(9, 3) == 3.0
    assert calculate_internal_metric(7, 2) == 3.5


# ---------------------------------------------------------------------------
# Test 8 - calculate_internal_metric raises ValueError on zero division
# ---------------------------------------------------------------------------

def test_calculate_internal_metric_raises_on_zero_division():
    """calculate_internal_metric(a, 0) must raise ValueError."""
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        calculate_internal_metric(10, 0)


# ---------------------------------------------------------------------------
# Test 9 (NEW) - ENVIRONMENT is read from env vars, not hardcoded
# ---------------------------------------------------------------------------

def test_environment_is_read_from_env_vars(client):
    """Home route must reflect the ENVIRONMENT env var."""
    response = client.get("/")
    data = response.get_json()
    assert "environment" in data, (
        "Expected 'environment' key in the home route response"
    )
    assert data["environment"] == "testing", (
        f"Expected 'testing' but got '{data['environment']}'. "
        "config.py is not reading from os.environ."
    )
