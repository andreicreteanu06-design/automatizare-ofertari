"""Opt-in integration: TEST_MEMORY_DATABASE_URL must name a dedicated test database."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from app.memory import MemoryStore

pytestmark = pytest.mark.skipif(not os.getenv('TEST_MEMORY_DATABASE_URL'), reason='Requires test Postgres')


def test_postgres_restart_ownership_atomicity_and_replay():
    dsn = os.environ['TEST_MEMORY_DATABASE_URL']
    store = MemoryStore(dsn)
    owner = 'test-' + uuid4().hex
    row = store.create(owner, 'Integration', 'Persistent history')
    cid = row['id']
    try:
        req = uuid4()
        result = {'answer': '12 kg', 'evidence': [{'id': 'a' * 24, 'quote': '12 kg'}]}
        first = store.append(owner, cid, 0, req, 'Question', result)
        # New repository instance = no Python object cache involved in persistence.
        restarted = MemoryStore(dsn)
        assert restarted.load(owner, cid)['messages'][1]['data'] == first
        assert restarted.append(owner, cid, 0, req, 'Question', result) == first
        with pytest.raises(HTTPException) as error:
            restarted.load('other-owner', cid)
        assert error.value.status_code == 404
        def append(_):
            try:
                restarted.append(owner, cid, 1, uuid4(), 'Concurrent', result)
                return 200
            except HTTPException as e:
                return e.status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(append, range(2))) == [200, 409]
        restarted.reference(owner, cid, 'a' * 24, 'Human review, not a fact')
        restored = restarted.load(owner, cid)
        assert restored['version'] == 2 and len(restored['messages']) == 4
        assert restored['references'][0]['note'] == 'Human review, not a fact'
        restarted.correct(owner, cid, req, ['a' * 24], 'Recheck the mass')
        another_restart = MemoryStore(dsn)
        assert another_restart.corrections(owner, 'Integration')[0]['note'] == 'Recheck the mass'
        assert another_restart.corrections('other-owner', 'Integration') == []
        assert another_restart.corrections(owner, 'Different project') == []
    finally:
        with store.connect() as conn:
            conn.execute('DELETE FROM chat_conversation WHERE id=%s AND owner_hash=%s', (cid, owner))
