import pytest

from src.database import Spend


@pytest.mark.freeze_time("2017-05-21")
def test_user_get_spend(user_with_spend, session):
    expected_spend = Spend(requests=60, completion_tokens=6000, prompt_tokens=12000)
    assert user_with_spend.get_spend(session) == expected_spend
