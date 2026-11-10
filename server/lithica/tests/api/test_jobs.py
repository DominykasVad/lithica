import pytest

from lithica import db, model, registry
from lithica.func import jobs, users
from lithica.tests.api.http import shipped_config


@pytest.fixture
def site(config_injector, tmp_path, user_factory):
    config_injector(shipped_config(str(tmp_path)))
    registry.use(
        [
            registry.Module(
                "worker", job_types=[registry.JobType("record", lambda p: None)]
            )
        ]
    )
    for i in range(3):
        job = jobs.enqueue("record", {"secret": i})
        if i == 1:
            job.status = "failed"
    db.session.commit()
    return user_factory(rank=model.User.RANK_ADMINISTRATOR)


def test_list_and_detail(client, site):
    result = client.get("/jobs", user=site, query={"limit": 1, "offset": 1}).json()
    assert result["total"] == 3
    assert len(result["results"]) == 1
    assert result["results"][0]["id"] == 2
    assert "payload" not in result["results"][0]
    assert result["results"][0]["user"] is None
    assert "userId" not in result["results"][0]
    detail = client.get("/job/2", user=site)
    assert detail.status_code == 200
    assert detail.json()["payload"] == {"secret": 1}
    result = client.get(
        "/jobs", user=site, query={"status": "failed", "type": "record"}
    ).json()
    assert result["total"] == 1
    assert (
        client.get("/jobs", user=site, query={"type": "missing"}).json()["total"] == 0
    )
    assert client.get("/jobs", user=site, query={"status": "wrong"}).status_code == 400
    assert client.get("/job/999", user=site).status_code == 404


@pytest.mark.parametrize("path", ["/jobs", "/job/1"])
def test_privileges_and_app_tokens(client, site, user_factory, monkeypatch, path):
    assert client.get(path, user=user_factory()).status_code == 403
    monkeypatch.setattr(
        "lithica.func.app_token_rights.current_rights",
        lambda: ("read", "write", "upload"),
    )
    assert client.get(path, user=site).status_code == 403


def test_real_administrator_app_token_refused(client, site):
    import base64

    from lithica.func import app_tokens

    site.name = "jobs-admin"
    db.session.add(site)
    db.session.flush()
    token, value = app_tokens.create_app_token(
        site, "jobs-test", ["read", "write", "upload"], True
    )
    db.session.add(token)
    db.session.commit()
    credentials = base64.b64encode(f"{site.name}:{value}".encode()).decode()
    for path in ("/jobs", "/job/1"):
        response = client.get(path, headers={"Authorization": "Token " + credentials})
        assert response.status_code == 403, response.text


@pytest.mark.parametrize("detail", [False, True])
def test_job_micro_user_and_deleted_user(
    client, site, user_factory, detail: bool
) -> None:
    from unittest.mock import patch

    owner = user_factory(name="job-owner", email="private@example.invalid")
    db.session.add(owner)
    db.session.flush()
    job = jobs.enqueue("record", {}, user=owner)
    db.session.commit()
    id = job.id
    path = f"/job/{id}" if detail else "/jobs"
    with patch(
        "lithica.func.jobs.users.serialize_micro_user", wraps=users.serialize_micro_user
    ) as serialize_user:
        answer = client.get(path, user=site)
        assert answer.status_code == 200, answer.text
        value = answer.json() if detail else answer.json()["results"][0]
        assert value["user"]["name"] == "job-owner"
        assert set(value["user"]) == {"name", "avatarUrl"}
        assert "userId" not in value
        assert serialize_user.called
        assert all(
            call.kwargs["auth_user"] is site for call in serialize_user.call_args_list
        )
    db.session.delete(owner)
    db.session.commit()
    db.session.expunge_all()
    answer = client.get(path, user=site)
    assert answer.status_code == 200, answer.text
    value = answer.json() if detail else answer.json()["results"][0]
    assert value["user"] is None
