from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


client = TestClient(app)


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_auth_profile_and_tournament_flow():
    # register + login first user and bootstrap admin
    client.post('/auth/register', data={'email': 'admin@test.com', 'password': 'pass'})
    client.post('/auth/login', data={'email': 'admin@test.com', 'password': 'pass'}, follow_redirects=False)
    client.post('/profile/edit', data={'full_name': 'Admin', 'email': 'admin@test.com', 'school_name': 'S', 'contact_info': 'c'})
    client.get('/bootstrap-admin', follow_redirects=False)

    now = datetime.utcnow()
    res = client.post('/tournaments', data={
        'title': 'T1',
        'description': 'D',
        'rules': 'R',
        'start_at': (now + timedelta(days=2)).isoformat(timespec='seconds'),
        'registration_open_at': (now - timedelta(days=1)).isoformat(timespec='seconds'),
        'registration_close_at': (now + timedelta(days=1)).isoformat(timespec='seconds'),
        'team_member_limit': 4,
        'round_title': 'Task 1',
        'round_description': 'Build',
        'tech_requirements': 'FastAPI',
        'must_have_csv': 'auth,leaderboard',
        'round_starts_at': now.isoformat(timespec='seconds'),
        'round_deadline_at': (now + timedelta(days=2)).isoformat(timespec='seconds'),
    }, follow_redirects=False)
    assert res.status_code == 303
    tid = int(res.headers['location'].split('/')[-1])

    # captain
    client.post('/auth/register', data={'email': 'capt@test.com', 'password': 'pass'})
    client.post('/auth/login', data={'email': 'capt@test.com', 'password': 'pass'}, follow_redirects=False)
    client.post('/profile/edit', data={'full_name': 'Cap', 'email': 'capt@test.com', 'school_name': 'S', 'contact_info': 'c'})
    reg = client.post(f'/tournaments/{tid}/register-team', data={
        'team_name': 'Alpha',
        'member_emails_csv': 'm1@test.com,m2@test.com',
        'member_names_csv': 'M1,M2',
    }, follow_redirects=False)
    assert reg.status_code == 303

    page = client.get(f'/tournaments/{tid}')
    assert page.status_code == 200
    assert 'Alpha' in page.text or 'Task 1' in page.text
