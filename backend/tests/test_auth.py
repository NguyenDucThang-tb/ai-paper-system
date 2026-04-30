def test_register_and_login_email(auth_client):
    register_payload = {
        "email": "newuser@example.com",
        "password": "secret123",
        "full_name": "New User",
    }
    register_res = auth_client.post("/api/v1/auth/register", json=register_payload)
    assert register_res.status_code == 200
    register_data = register_res.json()
    assert register_data["email"] == "newuser@example.com"
    assert register_data["role"] == "user"

    login_payload = {
        "email": "newuser@example.com",
        "password": "secret123",
        "device_id": "pytest-device",
    }
    login_res = auth_client.post("/api/v1/auth/login/email", json=login_payload)
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert "access_token" in login_data
    assert "refresh_token" in login_data
    assert login_data["user"]["email"] == "newuser@example.com"


def test_refresh_token_flow(auth_client):
    auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "refresh@example.com",
            "password": "secret123",
            "full_name": "Refresh User",
        },
    )

    login_res = auth_client.post(
        "/api/v1/auth/login/email",
        json={
            "email": "refresh@example.com",
            "password": "secret123",
            "device_id": "pytest-device",
        },
    )
    assert login_res.status_code == 200
    refresh_token = login_res.json()["refresh_token"]

    refresh_res = auth_client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": refresh_token,
            "device_id": "pytest-device",
        },
    )
    assert refresh_res.status_code == 200
    refresh_data = refresh_res.json()
    assert refresh_data["token_type"] == "bearer"
    assert refresh_data["user"]["email"] == "refresh@example.com"
