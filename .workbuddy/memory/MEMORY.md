# Ticko 项目记忆

Windows 桌面端「电脑使用时长统计 + 桌宠 + AI 陪伴」应用。纯标准库编写，内嵌 Python 3.13.12 运行时（python/ 目录），根目录 Ticko.exe 自包含启动器。

## 入口与启动流程
- 启动入口：`app/main_app.py`（main() 在 main_app.py:1187）。被根 Ticko.exe 调用。
- 单实例：Local\TickoSingleInstance 互斥量（main_app.py:31）。
- 后端：App 调用 `usage.start_backend(serve_in_thread=True)` 起本地 HTTP 服务（app.py:2175），默认 127.0.0.1:8765。
- 主面板：pywebview(gui="edgechromium") 加载本地 `/` -> dashboard.html。
- 系统托盘：pystray（`start_tray()` main_app.py:1136）。
- 桌宠：PetView（原生 Win32 UpdateLayeredWindow 透明窗体）独立线程运行（main_app.py:1265）。

## 后端核心 app/app.py（最关键，~2245 行）
- 常量 app.py:42-53：SAMPLE_INTERVAL=3，AWAY_THRESHOLD=300(5min)，SLEEP_THRESHOLD=30，PORT=8765，LOCK_PROCESS_NAMES。
- SCHEMA app.py:569-617：snapshots / segments / category_daily_stats / daily_stats（active/away/system）/ app_daily_stats / state_transitions / meta（KV 配置+心跳恢复）。
- Storage 类 app.py:630（SQLite 封装，get_meta/set_meta）。Tracker 类 app.py:838（每3秒 tick 采集前台窗口+空闲+锁屏；_close() 拆分小时桶并写入三本账，午夜切开）。
- Handler app.py:1120：本地 REST API + 静态文件。GET 路由 app.py:1602-1673，POST app.py:1177-。聚合接口 api_dashboard() app.py:1836。
- 数据保留：SNAPSHOT_KEEP_DAYS=30，SEGMENT_KEEP_DAYS=365（Storage.cleanup app.py:822）。

## 桌宠 pet_*
- pet_engine.py：行为状态机（wander/follow/still 模式，台词/互动等级），台词常量 LINES/REACT_LINES 等（pet_engine.py:10-51）。
- pet_geom.py：尺寸档位 SIZE_H={小:187,中:238,大:306}（pet_geom.py:4）。
- pet_view.py：Win32 渲染层（透明窗体+气泡）。
- pet_packs.py：自定义角色包（data/pets/<id>/，pack.json）。
- pet/pet.html + pet/sprites/* + pet/generated/*：前端立绘/渲染资源。状态经 window.__petApply(payload) 注入（main_app.py:488）。

## AI 伴侣 companion_*
- companion.py：状态翻译层 build_snapshot() companion.py:18（companion/focus/quiet 行为模式）。
- companion_ai.py：LLM 客户端 generate() companion_ai.py:196（OpenAI/Ollama/DeepSeek 兼容）；PERSONA_TEXT、LEVEL_POLICIES、MAX_REPLY=96、解析 [action:...]（companion_ai.py:11-221）。
- companion_templates.py：离线模板 SCENES（10 场景，{{占位符}}）。

## 分类 classify*
- classify.py：分类引擎 classify() classify.py:222（站点关键词->exe白名单->标题关键词->学习词库->浏览器默认娱乐）；CATEGORIES=("学习","娱乐","工作","社交","系统","其他") classify.py:20。
- classify_words.py：内置词库 LEARN_WORDS / FUN 站点 / EXCLUDE_LEARN（决定浏览器网页学习还是娱乐）。

## 其它模块
- window_space.py：纯几何数据模型，当前桌宠未实际用。
- goals_util.py：每日目标/忽略名单 parse_duration_text、should_credit_app（忽略 ticko/explorer/lockapp）。
- pomodoro_util.py：内存番茄钟（默认 25/5）。
- sound_util.py：本地提醒音（chime/wood/ping/urgent WAV）。
- speech_util.py：Vosk 离线输入 + Edge-TTS/Piper 离线播报。
- theme_util.py：主题包校验。download_kokoro.py：可选下载 Kokoro TTS。
- stop.py：优雅停止（POST /api/shutdown + taskkill）。
- selftest.py：离线 unittest 套件（`python/python.exe -m app.selftest`）。

## 运行/配置要点
- 配置全在 meta 表（明文，含 ai_api_key 明文存，注意安全）。
- 当前 meta 实测：show_pet=1, pet_mode=wander, pet_size=大, ai_enabled=1, ai_provider=openai, ai_base_url=https://api.deepseek.com, ai_model=deepseek-v4-flash, ai_persona=cheerful, companion_behavior=companion, theme_id=td96cecf3d94a。
- 运行时缓存放 APPDATA/Ticko/webview_cache。日志 data/app.log。
