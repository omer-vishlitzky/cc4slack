import pytest

from router.thread_store import RedisThreadStore, ThreadState


@pytest.fixture
def store() -> RedisThreadStore:
    import fakeredis.aioredis

    s = RedisThreadStore(redis_url="redis://fake")
    s._redis = fakeredis.aioredis.FakeRedis()
    return s


def make_thread_state(*, channel: str = "C1", thread_ts: str = "T1") -> ThreadState:
    return ThreadState(channel=channel, thread_ts=thread_ts, message_ts="M1")


@pytest.mark.asyncio
async def test_save_and_get_auth_token(*, store: RedisThreadStore) -> None:
    await store.save_auth_token(slack_user_id="U111", auth_token="tok-abc")
    result = await store.get_auth_token(slack_user_id="U111")
    assert result == "tok-abc"


@pytest.mark.asyncio
async def test_get_nonexistent_auth_token(*, store: RedisThreadStore) -> None:
    result = await store.get_auth_token(slack_user_id="U999")
    assert result is None


@pytest.mark.asyncio
async def test_revoke_auth_token(*, store: RedisThreadStore) -> None:
    await store.save_auth_token(slack_user_id="U111", auth_token="tok-abc")
    await store.revoke_auth_token(slack_user_id="U111")
    result = await store.get_auth_token(slack_user_id="U111")
    assert result is None


@pytest.mark.asyncio
async def test_save_auth_token_overwrites_previous(*, store: RedisThreadStore) -> None:
    await store.save_auth_token(slack_user_id="U111", auth_token="old-token")
    await store.save_auth_token(slack_user_id="U111", auth_token="new-token")
    result = await store.get_auth_token(slack_user_id="U111")
    assert result == "new-token"


@pytest.mark.asyncio
async def test_save_and_load_thread_state(*, store: RedisThreadStore) -> None:
    state = make_thread_state()
    await store.save_thread_state(slack_user_id="U111", thread_key="C1:T1", state=state)
    loaded = await store.load_thread_state(slack_user_id="U111", thread_key="C1:T1")
    assert loaded is not None
    assert loaded.channel == "C1"


@pytest.mark.asyncio
async def test_load_nonexistent_thread_state(*, store: RedisThreadStore) -> None:
    result = await store.load_thread_state(slack_user_id="U111", thread_key="C1:T1")
    assert result is None


@pytest.mark.asyncio
async def test_delete_thread_state(*, store: RedisThreadStore) -> None:
    state = make_thread_state()
    await store.save_thread_state(slack_user_id="U111", thread_key="C1:T1", state=state)
    await store.delete_thread_state(slack_user_id="U111", thread_key="C1:T1")
    result = await store.load_thread_state(slack_user_id="U111", thread_key="C1:T1")
    assert result is None


@pytest.mark.asyncio
async def test_load_all_thread_states(*, store: RedisThreadStore) -> None:
    s1 = make_thread_state(channel="C1")
    s2 = make_thread_state(channel="C2")
    await store.save_thread_state(slack_user_id="U111", thread_key="C1:T1", state=s1)
    await store.save_thread_state(slack_user_id="U111", thread_key="C2:T2", state=s2)
    all_states = await store.load_all_thread_states(slack_user_id="U111")
    assert len(all_states) == 2
    assert all_states["C1:T1"].channel == "C1"
    assert all_states["C2:T2"].channel == "C2"


@pytest.mark.asyncio
async def test_load_all_empty(*, store: RedisThreadStore) -> None:
    all_states = await store.load_all_thread_states(slack_user_id="U999")
    assert all_states == {}
