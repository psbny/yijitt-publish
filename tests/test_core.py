# -*- coding: utf-8 -*-
r"""文件简介：时间戳解析 / 类型判定 / 标题 / 计费 的离线单测。

夹具全部来自后台真实数据（2026-11-04 勘查）与 F:\ 里真实的 srt 文件。
运行：python -m pytest tests -q   或   python tests/test_core.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tarot_pipeline import core


# ------------------------------------------------ 真实后台数据夹具

CHAPTER_ALL_SIGNS = (
    "白羊座 — 00:02:11\r\n金牛座 — 00:15:33\r\n双子座 — 00:29:45\r\n巨蟹座 — 00:46:04\r\n"
    "狮子座 — 00:58:35\r\n处女座 — 01:16:16\r\n天秤座 — 01:34:45\r\n天蝎座 — 01:49:33\r\n"
    "射手座 — 02:06:47\r\n摩羯座 — 02:17:57\r\n水瓶座 — 02:32:33\r\n双鱼座 — 02:47:28"
)
CHAPTER_PICK = "黑手链 — 00:00:24\r\n黄手链 — 00:06:56"
YT_STYLE = "00:00 The Fog Breaks Today\n03:21 This Found You\n07:44 What Comes Next"


def test_parse_backend_format():
    chs = core.parse_chapters(CHAPTER_ALL_SIGNS)
    assert len(chs) == 12, len(chs)
    assert chs[0].name == "白羊座" and chs[0].seconds == 131
    assert chs[-1].line() == "双鱼座 — 02:47:28"


def test_parse_youtube_style():
    chs = core.parse_chapters(YT_STYLE)
    assert len(chs) == 3
    assert chs[0].name == "The Fog Breaks Today" and chs[0].seconds == 0
    assert chs[1].seconds == 201


def test_parse_time_first_cn():
    chs = core.parse_chapters("02:11 金牛座\n15:33 双子座")
    assert [c.name for c in chs] == ["金牛座", "双子座"]


def test_parse_english_zodiac():
    chs = core.parse_chapters("Aries 00:02:11\nTaurus 00:15:33\nGemini 00:29:45")
    assert chs[0].name == "白羊座"
    assert chs[1].name == "金牛座"


def test_parse_ignores_noise():
    txt = "Subscribe: https://x.com/a\n#tarot #love\n音乐\n00:00 Intro"
    chs = core.parse_chapters(txt)
    assert [c.name for c in chs] == ["Intro"]


def test_classify():
    # 用户 m03155：废除"按时间戳个数判类型"。全星座看标题、选组看标题、其余都是能量。
    # 全星座：标题写 all signs
    assert core.classify([], 0, "ALL SIGNS Tarot Reading") == core.TYPE_ALL_SIGNS
    assert core.classify([], 0, "全星座：现在有什么正被隐藏") == core.TYPE_ALL_SIGNS
    # 全星座兜底：标题没写，但章节凑齐 10 个以上星座
    assert core.classify(core.parse_chapters(CHAPTER_ALL_SIGNS)) == core.TYPE_ALL_SIGNS
    # 选组：标题带互动塔罗 / pick a pile
    assert core.classify([], 0, "Pick a Crystal: What Is Coming Towards You") == core.TYPE_PICK
    assert core.classify([], 0, "互动塔罗：你今天让他感受到什么") == core.TYPE_PICK
    assert core.classify(core.parse_chapters(CHAPTER_PICK), 0, "选一组：黑手链还是黄手链") == core.TYPE_PICK
    # 其余一律能量（包括 45 分钟、有叙事章节的）
    assert core.classify([]) == core.TYPE_ENERGY
    assert core.classify([], 45 * 60) == core.TYPE_ENERGY
    assert core.classify([], 0, "THE SECRET SOCIETY Is TERRIFIED Of YOU") == core.TYPE_ENERGY


def test_build_title():
    assert core.build_title("Aura", core.TYPE_ALL_SIGNS, "让我们偷偷窥探一下他们") == "【Aura】【全星座】让我们偷偷窥探一下他们"
    assert core.build_title("Deepa", core.TYPE_ENERGY, "你现在需要知道什么") == "【Deepa】你现在需要知道什么"
    assert core.build_title("杰伊塔罗", core.TYPE_PICK, "选一条手链") == "【杰伊塔罗】【选组】选一条手链"


def test_calc_cost_matches_backend():
    # 后台 5 条真实提交的 file_size 与扣费
    cases = [(55285, 15), (184238, 25), (213196, 30), (227708, 30), (27670, 10)]
    for size, coins in cases:
        got = core.calc_cost(size)
        assert got == coins, (size, got, coins)


def test_clean_srt_inline_tags_and_rollup():
    raw = (
        "1\n00:00:01,000 --> 00:00:03,000\n<00:00:01.240><c>hello</c> there\n\n"
        "2\n00:00:03,000 --> 00:00:05,000\nhello there my friend\n\n"
        "3\n00:00:05,000 --> 00:00:06,000\n[Music]\n\n"
        "4\n00:00:06,000 --> 00:00:09,000\nthis is the end.\n"
    )
    out = core.clean_srt(raw, merge=False)
    assert "<" not in out and "[Music]" not in out
    assert "hello there my friend" in out


def test_sniff_encoding_bom():
    txt, enc = core.sniff_srt_encoding("\ufeffhi".encode("utf-8"))
    assert enc == "utf-8-sig" and txt == "hi"


def test_safe_filename():
    assert core.safe_filename('a/b:c*?"d') == "a_b_c_d"


# ---------------------------------------------------------------- 新增：候选过滤 / 章节净化 / 时间格式

def test_hhmmss_always_padded():
    """后台真实数据一律 HH:MM:SS，不足 1 小时也补 00:。"""
    assert core.Chapter("白羊座", 131).hhmmss() == "00:02:11"
    assert core.Chapter("天蝎座", 6573).hhmmss() == "01:49:33"
    assert core.Chapter("双鱼座", 10048).hhmmss() == "02:47:28"


def test_is_candidate_rejects_music_and_shorts():
    # 实测 @aurawesttarot7185 频道里混着这些音乐混音，时长 212~288s
    for title, dur in (("AWM - Two Hearts Aligned", 254),
                       ("Beach House - Space Song Alt-Cover", 279),
                       ("LMFAO - SEXY AND I KNOW IT MASH UP (BRITNEY SPEARS INSTRUMENTAL)", 230)):
        ok, why = core.is_candidate(title, dur)
        assert not ok, (title, why)
    ok, _ = core.is_candidate("ALL SIGNS What's Ahead This Week", 0)
    assert not ok  # Shorts / 未开播
    ok, _ = core.is_candidate("ALL SIGNS Current Feelings", 7793)
    assert ok
    ok, _ = core.is_candidate("Scorpio You're Done Chasing", 1379)
    assert ok


def test_clean_chapters_all_signs_drops_intro():
    desc = ("Intro - 00:00\nScorpio - 01:05\nPisces - 47:15\nAries - 55:40\nTaurus - 1:04:32\n"
            "Gemini - 1:13:20\nCancer - 1:22:18\nLeo - 1:31:08\nVirgo - 1:41:00\nLibra - 1:50:00\n"
            "Sagittarius - 2:00:00\nCapricorn - 2:10:00\nAquarius - 2:20:00")
    chs = core.parse_chapters(desc)
    assert core.classify(chs, 7793) == core.TYPE_ALL_SIGNS
    kept = core.clean_chapters(chs, core.TYPE_ALL_SIGNS)
    assert len(kept) == 12
    assert all(c.name != "Intro" for c in kept)
    # 保持视频原始先后（时间递增），不强制白羊开头
    assert kept[0].name == "天蝎座"


def test_clean_chapters_pick_keeps_options():
    desc = "黑手链 - 00:00:24\n黄手链 - 00:06:56"
    chs = core.parse_chapters(desc)
    assert core.classify(chs, 2000, "选一组：黑手链还是黄手链") == core.TYPE_PICK
    kept = core.clean_chapters(chs, core.TYPE_PICK)
    assert [c.name for c in kept] == ["黑手链", "黄手链"]
    assert core.format_chapter_block(kept) == "黑手链 — 00:00:24\r\n黄手链 — 00:06:56"


def test_clean_chapters_energy_is_empty():
    assert core.clean_chapters(core.parse_chapters(""), core.TYPE_ENERGY) == []


# ------------------------------------------------ m01172 新增规则

def test_duration_filter_energy_over_30min():
    # 能量超过 30 分钟不更（2026-11-07 用户把上限从 40 分钟改成 30 分钟，rules.yaml 是唯一来源）
    assert core.duration_filter(core.TYPE_ENERGY, 31 * 60)
    assert core.duration_filter(core.TYPE_ENERGY, 40 * 60)
    assert core.duration_filter(core.TYPE_ENERGY, 30 * 60) is None
    assert core.duration_filter(core.TYPE_ENERGY, 15 * 60) is None


def test_duration_filter_all_signs_over_4h():
    # 全星座超过 4 小时不更
    assert core.duration_filter(core.TYPE_ALL_SIGNS, 4 * 3600 + 60)
    assert core.duration_filter(core.TYPE_ALL_SIGNS, 186 * 60) is None


def test_zodiac_names_in_spanish():
    # 塔罗女王是西语频道，要用西语星座名才认得出来
    assert core.zodiac_names_in("PISCIS! ¡ESTO NO ES COINCIDENCIA!") == {"双鱼座"}
    assert core.zodiac_names_in("GÉMINIS! ¡HASTA LA MADRE!") == {"双子座"}
    assert core.zodiac_names_in("ALL SIGNS - Lets Spy on Them") == set()


def test_single_sign_batch_detection():
    # 一个星座一条、覆盖 12 星座 -> 单星座批量，按规则不更
    batch = ["PISCIS a", "GÉMINIS b", "LIBRA c", "CAPRICORNIO d", "SAGITARIO e",
             "LEO f", "ESCORPIO g", "VIRGO h", "ACUARIO i", "ARIES j", "CÁNCER k", "TAURO l"]
    assert core.looks_like_single_sign_batch(batch)
    # 全星座视频标题不带单个星座名 -> 不是批量
    assert not core.looks_like_single_sign_batch(
        ["ALL SIGNS 💘 Their Feelings", "ALL SIGNS - Lets Spy on Them"] * 4)
    # 条数不够不判 batch
    assert not core.looks_like_single_sign_batch(["ARIES a", "LEO b"])


def test_schedule_ep_slots_roll_5min():
    from tarot_pipeline import schedule as sch
    assert sch.ep_slots(3) == [(8, 5), (9, 5), (10, 5)]
    # 超过 16 个进第二轮，分钟 +5
    slots = sch.ep_slots(18)
    assert slots[16] == (8, 10)
    assert slots[17] == (9, 10)


def test_schedule_all_signs_slots():
    from tarot_pipeline import schedule as sch
    # 用户给的例子：9:15 / 14:15 / 21:15，其次 16:15 / 19:15
    assert sch.as_slots(5) == [(9, 15), (14, 15), (21, 15), (16, 15), (19, 15)]


def test_schedule_plan_avoids_occupied_and_prices():
    import datetime as dt
    from tarot_pipeline import schedule as sch
    items = [
        {"cn": "Wisdom", "vtype": "energy"},
        {"cn": "Aura", "vtype": "all_signs"},
    ]
    date = dt.date(2026, 11, 5)
    out = sch.plan(items, date, occupied={(9, 15), (16, 15)})
    assert [x["hhmm"] for x in out] == ["08:05", "14:15"]
    assert out[0]["price"] == 29 and out[1]["price"] == 79
    # 价格换算：79 分 = ¥0.79
    assert out[1]["ts"] == int(dt.datetime(2026, 11, 5, 14, 15,
                                           tzinfo=sch.TZ).timestamp())



def test_classify_no_chapters_ignores_memory():
    """m04376：完全没有章节时不能因为"这博主一般发选组"就判选组——那种是能量。"""
    assert core.classify([], 1159, "MENSAJE ESPECIAL DE HOY", core.TYPE_PICK) == core.TYPE_ENERGY
    assert core.classify([], 3000, "Weekly message", core.TYPE_ALL_SIGNS) == core.TYPE_ENERGY


def test_classify_uses_memory_only_with_chapters():
    chs = core.parse_chapters("a 00:00\nb 00:05\nc 00:09")
    assert core.classify(chs, 2000, "something", core.TYPE_PICK) == core.TYPE_PICK


def test_viewer_interaction_titles():
    """m05854：观众互动类（现场给观众做解读）不再更新。"""
    # Evan 真实标题
    assert core.looks_viewer_interaction(
        "Astrologer Reads Audience Members Based on Their Big 3...and the Accuracy is Shocking")
    assert core.looks_viewer_interaction(
        "We Did Live Astrology Readings During an Eclipse...And it Got Personal")
    # 正常的星座/周运不该命中
    assert not core.looks_viewer_interaction(
        "November 2026 Horoscopes: Each Zodiac Sign is Staring into the Abyss")
    assert not core.looks_viewer_interaction(
        "Weekly Astro Live: The Week Ahead, Plus Pluto in Aquarius Impact on All 12 Signs")
    # 付费解读仍走自己的分支（不混）
    assert not core.looks_viewer_interaction("LIVE READINGS 25$ PER QUESTION!! All Signs")
    assert core.looks_paid_live("LIVE READINGS 25$ PER QUESTION!! All Signs")


def test_is_candidate_skips_viewer_interaction():
    ok, why = core.is_candidate(
        "Astrologer Reads Audience Members Based on Their Big 3", 2400, "")
    assert not ok and "观众互动" in why, why
    ok, why = core.is_candidate("November 2026 Horoscopes: Each Zodiac Sign", 2400, "")
    assert ok, why


def test_premiere_treated_as_live_future():
    """m05854：首映（Premieres in N）按直播预告处理，记 expect_at，到点再试。"""
    import datetime as dt
    import time as _t

    from tarot_pipeline import pipeline as P
    from tarot_pipeline import youtube as yt

    orig = yt.video_info

    def boom(vid, proxy=None):
        raise RuntimeError(
            "ERROR: [youtube] %s: Premieres in 36 minutes" % vid)

    yt.video_info = boom
    try:
        stub = yt.Video(video_id="9-HhGzPrJN4", title="premiere test")
        item = {"blogger": {"cn": "Sister", "handle": "@x", "name": "x"}, "stub": stub}
        res = P.process_one({}, None, item)
    finally:
        yt.video_info = orig
    assert res["status"] == "live_future", res
    assert "首映" in res["reason"], res["reason"]
    exp = dt.datetime.fromisoformat(res["expect_at"]).timestamp()
    assert abs(exp - (_t.time() + 36 * 60)) < 120, (exp, _t.time())


# ------------------------------------------------ m06495：多语言星座名 / hashtag

_ITALIAN = ("Introduzione 00:00\r\nAriete 00:12\r\nToro 12:40\r\nGemelli 24:05\r\n"
            "Cancro 35:20\r\nLeone 46:11\r\nVergine 57:30\r\nBilancia 1:08:00\r\n"
            "Scorpione 1:19:20\r\nSagittario 1:30:40\r\nCapricorno 1:41:00\r\n"
            "Acquario 1:52:10\r\nPesci 2:03:00")

_RUSSIAN = ("Вступление 00:00\r\nОвен 01:12\r\nТелец 12:40\r\nБлизнецы 24:05\r\n"
            "Рак 35:20\r\nЛев 46:11\r\nДева 57:30\r\nВесы 1:08:00\r\n"
            "Скорпион 1:19:20\r\nСтрелец 1:30:40\r\nКозерог 1:41:00\r\n"
            "Водолей 1:52:10\r\nРыбы 2:03:00")

_POLISH = ("Wstęp 00:00\r\nBaran 01:12\r\nByk 12:40\r\nBliźnięta 24:05\r\n"
           "Rak 35:20\r\nLew 46:11\r\nPanna 57:30\r\nWaga 1:08:00\r\n"
           "Skorpion 1:19:20\r\nStrzelec 1:30:40\r\nKoziorożec 1:41:00\r\n"
           "Wodnik 1:52:10\r\nRyby 2:03:00")


def _assert_all_signs(text, dur=7200):
    chs = core.parse_chapters(text)
    assert len(core.zodiac_hits_names(chs)) == 12, [c.name for c in chs]
    # 标题里没有 all signs，全靠章节认 —— 正是今天丢掉的那批
    assert core.classify(chs, dur, "no all signs in title") == core.TYPE_ALL_SIGNS


def test_zodiac_italian_chapters():
    """m06495 漏洞1：意大利语章节以前一个都认不出，被判 energy 再撞 30 分钟上限。"""
    _assert_all_signs(_ITALIAN)


def test_zodiac_russian_chapters():
    _assert_all_signs(_RUSSIAN)


def test_zodiac_polish_chapters():
    _assert_all_signs(_POLISH)


def test_zodiac_alias_needs_word_boundary():
    """外语短词必须整词匹配，不能子串误伤（`toro` 不该命中 Toronto）。"""
    assert core._norm_zodiac("Toronto") == "Toronto"
    assert core._norm_zodiac("Leonardo") == "Leonardo"
    assert core._norm_zodiac("jewellery") == "jewellery"
    assert core._norm_zodiac("Rak 35:20") == "巨蟹座"
    assert core._norm_zodiac("Lew — 46:11") == "狮子座"
    assert core._norm_zodiac("Leo ♌") == "狮子座"


def test_hashtag_tarot_no_longer_kills_long_video():
    """m06495 漏洞2：Kitty 那种两小时全星座标题挂 #tarot，以前被当 Shorts 丢掉。"""
    ok, why = core.is_candidate("ALL SIGNS TAROT READING #tarot #tarotreading", 7200, "")
    assert ok, why
    ok, why = core.is_candidate("Daily energy #fyp", 1200, "")
    assert ok, why


def test_shorts_hashtag_still_filters_short_clip():
    ok, why = core.is_candidate("quick pull #shorts", 540, "")
    assert not ok and "Shorts" in why, why


def test_upload_date_in_window_backfill():
    """m06508 §30：回扫窗口 11-01~11-08 时，Kitty 6 月/7 月的老视频必须被判出窗口。"""
    ws = time.mktime(time.strptime("2026-11-01 00:00", "%Y-%m-%d %H:%M"))
    we = time.mktime(time.strptime("2026-11-08 23:59", "%Y-%m-%d %H:%M"))
    assert not core.upload_date_in_window("20260615", ws, we)
    assert not core.upload_date_in_window("20260722", ws, we)
    assert not core.upload_date_in_window("20261014", ws, we)
    assert not core.upload_date_in_window("20261031", ws, we)
    assert core.upload_date_in_window("20261101", ws, we)
    assert core.upload_date_in_window("20261108", ws, we)
    # 日界：窗口末日之后的次日 0 点前上传，仍应算进来
    assert core.upload_date_in_window("20261109", ws, we)


def test_upload_date_in_window_daily_across_midnight():
    """每天 21:00~次日 21:00 的窗口跨两个日期，日期精度不能误杀。"""
    ws = time.mktime(time.strptime("2026-11-08 21:00", "%Y-%m-%d %H:%M"))
    we = time.mktime(time.strptime("2026-11-09 21:00", "%Y-%m-%d %H:%M"))
    assert core.upload_date_in_window("20261108", ws, we)
    assert core.upload_date_in_window("20261109", ws, we)
    assert not core.upload_date_in_window("20261107", ws, we)
    # 认不出或空值一律放行（宁可放过，不要因为没日期丢新视频）
    assert core.upload_date_in_window("", ws, we)
    assert core.upload_date_in_window("unknown", ws, we)


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as e:
                fails += 1
                print("FAIL", name, "->", type(e).__name__, e)
    print("\n%d failed" % fails)
    sys.exit(1 if fails else 0)
