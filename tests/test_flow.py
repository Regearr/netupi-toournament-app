from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.database import Base, engine


client = TestClient(app)


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_core_flow():
    client.post('/users/seed')
    now = datetime.utcnow()
    t_res = client.post('/tournaments', data={
        'title': 'Test Tournament',
        'description': 'Desc',
        'rules': 'Rules',
        'start_at': (now + timedelta(days=1)).isoformat(timespec='seconds'),
        'registration_open_at': (now - timedelta(days=1)).isoformat(timespec='seconds'),
        'registration_close_at': (now + timedelta(days=1)).isoformat(timespec='seconds'),
        'team_member_limit': 4,
    }, follow_redirects=False)
    assert t_res.status_code == 303
    loc = t_res.headers['location']
    tid = int(loc.split('/')[-1])

    reg = client.post(f'/tournaments/{tid}/register', data={
        'team_name': 'Alpha',
        'captain_name': 'Cap',
        'captain_email': 'cap@alpha.com',
        'member_names_csv': 'A,B',
        'member_emails_csv': 'a@alpha.com,b@alpha.com',
    }, follow_redirects=False)
    assert reg.status_code == 303

    round_res = client.post(f'/tournaments/{tid}/rounds', data={
        'title': 'Round 1',
        'description': 'Build app',
        'tech_requirements': 'FastAPI',
        'must_have_csv': 'auth,leaderboard',
        'starts_at': now.isoformat(timespec='seconds'),
        'deadline_at': (now + timedelta(days=2)).isoformat(timespec='seconds'),
    }, follow_redirects=False)
    assert round_res.status_code == 303

    t_page = client.get(f'/tournaments/{tid}')
    assert t_page.status_code == 200
    assert 'Round 1' in t_page.text
