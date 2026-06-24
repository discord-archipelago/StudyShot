import discord
from discord.ext import commands, tasks
import json
import random
import os

# ── 데이터 로드 헬퍼 ──────────────────────────────────────────
def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── 설정 로드 ─────────────────────────────────────────────────
config = load_json("config.json")
TOKEN = config["token"]
PREFIX = config.get("prefix", "!")

# ── 봇 설정 ──────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ── 패키지 목록 불러오기 ──────────────────────────────────────
def get_packages():
    packages = {}
    for fname in os.listdir("packages"):
        if fname.endswith(".json"):
            data = load_json(f"packages/{fname}")
            key = fname.replace(".json", "")
            packages[key] = data
    return packages

# ── 문제 출제 상태 관리 (채널별) ──────────────────────────────
active_questions = {}

# ── 자동 출제 태스크 관리 ─────────────────────────────────────
auto_quiz_tasks = {}

# ── 점수 관련 헬퍼 ────────────────────────────────────────────
def get_scores():
    return load_json("data/scores.json")

def add_score(user_id: str, username: str, amount: int = 1):
    scores = get_scores()
    if user_id not in scores:
        scores[user_id] = {"username": username, "score": 0}
    scores[user_id]["score"] += amount
    scores[user_id]["username"] = username
    save_json("data/scores.json", scores)
    return scores[user_id]["score"]

# ── 서버 설정 헬퍼 ────────────────────────────────────────────
def get_settings():
    return load_json("data/settings.json")

def save_settings(settings):
    save_json("data/settings.json", settings)

def get_guild_setting(guild_id: str):
    settings = get_settings()
    return settings.get(guild_id, {
        "package": "english_1",
        "interval": 0,
        "quiz_channel": None
    })

def update_guild_setting(guild_id: str, key: str, value):
    settings = get_settings()
    if guild_id not in settings:
        settings[guild_id] = {
            "package": "english_1",
            "interval": 0,
            "quiz_channel": None
        }
    settings[guild_id][key] = value
    save_settings(settings)

# ── 문제 뽑기 ─────────────────────────────────────────────────
def pick_question(package_key: str):
    packages = get_packages()
    if package_key not in packages:
        return None
    questions = packages[package_key]["questions"]
    return random.choice(questions)

# ── 정답 체크 ─────────────────────────────────────────────────
def check_answer(user_answer: str, correct_answer: str, q_type: str) -> bool:
    user = user_answer.strip().lower().replace(" ", "")

    if q_type == "ox":
        ox_map = {"o": "o", "0": "o", "ㅇ": "o", "x": "x", "ㅌ": "x"}
        user = ox_map.get(user, user)
        return user == correct_answer.lower()

    if q_type == "multiple_choice":
        return user == correct_answer.strip()

    correct_list = [a.strip().lower().replace(" ", "") for a in correct_answer.split(",")]
    return user in correct_list

# ── 문제 임베드 생성 ──────────────────────────────────────────
def make_quiz_embed(q: dict, package_name: str) -> discord.Embed:
    category_emoji = {"word": "📝", "grammar": "📖", "reading": "📚"}.get(q.get("category", ""), "❓")
    type_label = {"short_answer": "주관식", "multiple_choice": "객관식", "ox": "OX"}.get(q.get("type", ""), "")

    embed = discord.Embed(
        title=f"{category_emoji} 문제 출제! [{type_label}]",
        description=f"**{q['question']}**",
        color=0x5865F2
    )

    if q["type"] == "multiple_choice":
        choices_text = "\n".join([f"`{i+1}` {c}" for i, c in enumerate(q["choices"])])
        embed.add_field(name="보기", value=choices_text, inline=False)
        embed.set_footer(text=f"📦 {package_name} | 숫자로 답하세요 | 💡 힌트: !hint | ❌ 포기: !skip")
    elif q["type"] == "ox":
        embed.set_footer(text=f"📦 {package_name} | O 또는 X로 답하세요 | 💡 힌트: !hint | ❌ 포기: !skip")
    else:
        embed.set_footer(text=f"📦 {package_name} | 💡 힌트: !hint | ❌ 포기: !skip")

    return embed

# ══════════════════════════════════════════════════════════════
#  이벤트
# ══════════════════════════════════════════════════════════════

@bot.event
async def on_ready():
    print(f"✅ {bot.user} 로그인 완료!")
    print(f"📦 패키지: {list(get_packages().keys())}")

    settings = get_settings()
    for guild_id, cfg in settings.items():
        if cfg.get("interval", 0) > 0 and cfg.get("quiz_channel"):
            start_auto_quiz(int(guild_id), cfg["quiz_channel"], cfg["interval"], cfg["package"])

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    channel_id = message.channel.id

    if not message.content.startswith(PREFIX):
        if channel_id in active_questions and active_questions[channel_id]["active"]:
            q = active_questions[channel_id]
            if check_answer(message.content, q["answer"], q["type"]):
                active_questions[channel_id]["active"] = False
                new_score = add_score(str(message.author.id), message.author.display_name)

                embed = discord.Embed(
                    title="🎉 정답!",
                    description=f"**{message.author.mention}** 정답이에요!\n정답: `{q['answer']}`",
                    color=0x57F287
                )
                embed.set_footer(text=f"🏆 현재 점수: {new_score}점")
                await message.channel.send(embed=embed)
                return

    await bot.process_commands(message)

# ══════════════════════════════════════════════════════════════
#  명령어
# ══════════════════════════════════════════════════════════════

@bot.command(name="퀴즈", aliases=["quiz", "q"])
async def quiz(ctx):
    channel_id = ctx.channel.id
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"

    if channel_id in active_questions and active_questions[channel_id]["active"]:
        await ctx.send("⚠️ 아직 풀리지 않은 문제가 있어요! 먼저 맞혀보세요 :)")
        return

    cfg = get_guild_setting(guild_id)
    package_key = cfg.get("package", "english_1")
    packages = get_packages()

    if package_key not in packages:
        await ctx.send("❌ 선택된 패키지를 찾을 수 없어요.")
        return

    q = pick_question(package_key)
    active_questions[channel_id] = {
        "question": q["question"],
        "answer": q["answer"],
        "hint": q.get("hint", "힌트 없음"),
        "type": q["type"],
        "choices": q.get("choices", []),
        "active": True
    }

    embed = make_quiz_embed(q, packages[package_key]["name"])
    await ctx.send(embed=embed)

@bot.command(name="hint", aliases=["힌트"])
async def hint(ctx):
    channel_id = ctx.channel.id
    if channel_id not in active_questions or not active_questions[channel_id]["active"]:
        await ctx.send("❓ 현재 진행 중인 문제가 없어요. `!퀴즈` 로 시작해보세요!")
        return
    hint_text = active_questions[channel_id]["hint"]
    await ctx.send(f"💡 힌트: **{hint_text}**")

@bot.command(name="skip", aliases=["포기", "스킵"])
async def skip(ctx):
    channel_id = ctx.channel.id
    if channel_id not in active_questions or not active_questions[channel_id]["active"]:
        await ctx.send("❓ 현재 진행 중인 문제가 없어요.")
        return

    answer = active_questions[channel_id]["answer"]
    q_type = active_questions[channel_id]["type"]
    choices = active_questions[channel_id].get("choices", [])
    active_questions[channel_id]["active"] = False

    if q_type == "multiple_choice" and choices:
        try:
            answer_text = choices[int(answer) - 1]
            answer_display = f"{answer}번 - {answer_text}"
        except Exception:
            answer_display = answer
    else:
        answer_display = answer

    embed = discord.Embed(
        title="💊 탐아 드세요~",
        description=f"정답은 **`{answer_display}`** 이었어요!",
        color=0xED4245
    )
    await ctx.send(embed=embed)

@bot.command(name="랭킹", aliases=["ranking", "rank", "순위"])
async def ranking(ctx):
    scores = get_scores()
    if not scores:
        await ctx.send("아직 점수가 없어요! `!퀴즈` 로 시작해보세요 :D")
        return

    sorted_scores = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]

    embed = discord.Embed(title="🏆 StudyShot 랭킹", color=0xFEE75C)
    for i, (uid, data) in enumerate(sorted_scores[:10]):
        medal = medals[i] if i < 3 else f"`{i+1}.`"
        embed.add_field(
            name=f"{medal} {data['username']}",
            value=f"**{data['score']}점**",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(name="내점수", aliases=["myscore", "점수"])
async def my_score(ctx):
    scores = get_scores()
    uid = str(ctx.author.id)
    if uid not in scores:
        await ctx.send("아직 점수가 없어요! `!퀴즈` 로 시작해보세요 :D")
        return
    score = scores[uid]["score"]
    sorted_scores = sorted(scores.items(), key=lambda x: x[1]["score"], reverse=True)
    rank = next((i+1 for i, (k, _) in enumerate(sorted_scores) if k == uid), "?")

    embed = discord.Embed(
        title=f"📊 {ctx.author.display_name}의 점수",
        description=f"**{score}점** | 현재 **{rank}위**",
        color=0x5865F2
    )
    await ctx.send(embed=embed)

@bot.command(name="패키지", aliases=["package", "pkg"])
async def package_cmd(ctx, key: str = None):
    packages = get_packages()
    guild_id = str(ctx.guild.id) if ctx.guild else "dm"

    if key is None:
        embed = discord.Embed(title="📦 문제 패키지 목록", color=0x5865F2)
        cfg = get_guild_setting(guild_id)
        current = cfg.get("package", "english_1")
        for k, p in packages.items():
            is_current = "✅ " if k == current else ""
            q_count = len(p["questions"])
            embed.add_field(
                name=f"{is_current}`{k}`",
                value=f"{p['description']} ({q_count}문제)",
                inline=False
            )
        embed.set_footer(text="변경: !패키지 [패키지이름]")
        await ctx.send(embed=embed)
    else:
        if key not in packages:
            await ctx.send(f"❌ `{key}` 패키지가 없어요. `!패키지` 로 목록을 확인해보세요.")
            return
        update_guild_setting(guild_id, "package", key)
        await ctx.send(f"✅ 패키지를 **{packages[key]['name']}** 으로 변경했어요!")

@bot.command(name="자동", aliases=["auto"])
async def auto_quiz_cmd(ctx, interval: int = None):
    guild_id = str(ctx.guild.id) if ctx.guild else None
    if not guild_id:
        await ctx.send("❌ 서버에서만 사용 가능해요.")
        return

    if interval is None:
        cfg = get_guild_setting(guild_id)
        current = cfg.get("interval", 0)
        if current > 0:
            await ctx.send(f"⏱️ 현재 자동 출제: **{current}분** 간격\n끄려면 `!자동 0`")
        else:
            await ctx.send("⏱️ 자동 출제가 꺼져 있어요.\n켜려면 `!자동 [분]` (예: `!자동 10`)")
        return

    if interval == 0:
        stop_auto_quiz(int(guild_id))
        update_guild_setting(guild_id, "interval", 0)
        await ctx.send("⏹️ 자동 출제를 껐어요.")
        return

    if interval < 1:
        await ctx.send("❌ 최소 1분 이상이어야 해요.")
        return

    update_guild_setting(guild_id, "interval", interval)
    update_guild_setting(guild_id, "quiz_channel", ctx.channel.id)
    cfg = get_guild_setting(guild_id)
    start_auto_quiz(int(guild_id), ctx.channel.id, interval, cfg["package"])
    await ctx.send(f"⏱️ **{interval}분** 간격으로 자동 출제 시작! (이 채널에서)")

@bot.command(name="도움", aliases=["help", "명령어"])
async def help_cmd(ctx):
    embed = discord.Embed(title="📖 StudyShot 명령어", color=0x5865F2)
    cmds = [
        ("!퀴즈", "문제 출제 (주관식/객관식/OX 랜덤)"),
        ("!hint / !힌트", "현재 문제 힌트"),
        ("!skip / !포기", "현재 문제 포기 (탐아 💊)"),
        ("!랭킹", "점수 랭킹 보기"),
        ("!내점수", "내 점수 & 순위 보기"),
        ("!패키지", "패키지 목록 보기"),
        ("!패키지 [이름]", "패키지 변경"),
        ("!자동 [분]", "자동 출제 설정 (0=끄기)"),
        ("!도움", "명령어 목록"),
    ]
    for name, desc in cmds:
        embed.add_field(name=f"`{name}`", value=desc, inline=False)
    await ctx.send(embed=embed)

# ══════════════════════════════════════════════════════════════
#  자동 출제 태스크
# ══════════════════════════════════════════════════════════════

def start_auto_quiz(guild_id: int, channel_id: int, interval_min: int, package_key: str):
    stop_auto_quiz(guild_id)

    @tasks.loop(minutes=interval_min)
    async def _auto_quiz_task():
        await bot.wait_until_ready()
        channel = bot.get_channel(channel_id)
        if not channel:
            return
        if channel_id in active_questions and active_questions[channel_id]["active"]:
            return

        packages = get_packages()
        if package_key not in packages:
            return

        q = pick_question(package_key)
        active_questions[channel_id] = {
            "question": q["question"],
            "answer": q["answer"],
            "hint": q.get("hint", "힌트 없음"),
            "type": q["type"],
            "choices": q.get("choices", []),
            "active": True
        }
        embed = make_quiz_embed(q, packages[package_key]["name"])
        await channel.send(embed=embed)

    _auto_quiz_task.start()
    auto_quiz_tasks[guild_id] = _auto_quiz_task

def stop_auto_quiz(guild_id: int):
    if guild_id in auto_quiz_tasks:
        try:
            auto_quiz_tasks[guild_id].cancel()
        except Exception:
            pass
        del auto_quiz_tasks[guild_id]

# ══════════════════════════════════════════════════════════════
#  실행
bot.run(TOKEN)