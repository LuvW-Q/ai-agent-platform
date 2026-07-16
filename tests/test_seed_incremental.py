"""数字员工增量种子和本地技能执行回归测试。"""

from core.sandbox import sandbox
from database.session import SessionLocal
from models.agent import Agent
from models.skill import Skill
from seed import run_seed


def test_music_and_news_seed_is_idempotent_and_executable():
    run_seed()
    run_seed()

    db = SessionLocal()
    try:
        music_skill = db.query(Skill).filter(Skill.name == "随机音乐推荐").one()
        news_skill = db.query(Skill).filter(Skill.name == "新闻检索").one()
        music_agent = db.query(Agent).filter(Agent.name == "随机音乐").one()
        news_agent = db.query(Agent).filter(Agent.name == "新闻").one()

        assert music_agent.status == "published"
        assert news_agent.status == "published"
        assert music_agent.skill_ids == str(music_skill.id)
        assert news_agent.skill_ids == str(news_skill.id)

        music_result = sandbox.execute_function(
            music_skill.config,
            "execute",
            {},
        )
        assert music_result["success"] is True, music_result["error"]
        assert set(music_result["result"]) == {"song", "artist"}
        assert all(music_result["result"].values())

        news_result = sandbox.execute_function(
            news_skill.config,
            "execute",
            {"keyword": ""},
        )
        assert news_result["success"] is True, news_result["error"]
        assert set(news_result["result"]) == {"count", "items"}
        assert news_result["result"]["count"] == len(news_result["result"]["items"])
    finally:
        db.close()
