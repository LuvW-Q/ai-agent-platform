"""数字员工增量种子和本地技能执行回归测试。"""

import json

from core.builtin_skills import execute_builtin_skill
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

        music_handler = json.loads(music_skill.config)["handler"]
        music_result = execute_builtin_skill(music_handler, {}, db)
        assert set(music_result) == {"song", "artist"}
        assert all(music_result.values())

        news_handler = json.loads(news_skill.config)["handler"]
        news_result = execute_builtin_skill(news_handler, {"keyword": ""}, db)
        assert set(news_result) == {"count", "items"}
        assert news_result["count"] == len(news_result["items"])
    finally:
        db.close()
