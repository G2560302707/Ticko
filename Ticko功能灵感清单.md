# Ticko 功能灵感清单

> 基于通读 `app/` 全部源码后的功能扩展设想。按落地性价比与方向分类，每个点标注大致改动落点与难度（★ 低 / ★★ 中 / ★★★ 高）。
>
> 现有架构回顾：
> - 入口外壳：`main_app.py`（pywebview + pystray + Win32 透明桌宠）
> - 后端核心：`app.py`（每 3 秒采样、SQLite 三本账、本地 HTTP + REST API）
> - 桌宠：`pet_engine.py` / `pet_geom.py` / `pet_view.py` / `pet_packs.py`
> - AI 伴侣：`companion.py` / `companion_ai.py` / `companion_templates.py`
> - 分类：`classify.py` + `classify_words.py`
> - 其它：`goals_util.py`（目标）、`pomodoro_util.py`（番茄钟）、`sound_util.py`、`speech_util.py`、`theme_util.py`、`window_space.py`（当前未启用）

---

## 一、把半成品补完（性价比最高）

| 灵感 | 说明 | 落点 | 难度 |
|---|---|---|---|
| 启用 `window_space.py` | 让桌宠真正"爬"到窗口边缘、躲任务栏、跟随当前前台 App 自动换位置/姿势，和正在用的软件产生互动 | `pet_engine.py` + `window_space.py` | ★★ |
| Kokoro 离线音色接入 | `download_kokoro.py` 已下载模型但未接进播报链路，做成默认离线音色，断网也能语音 | `speech_util.py` | ★★ |
| 自定义角色包向导 | 上传 front/side/back 三张图 → 预览 → 裁切 → 生成角色包，做成可视化小向导 | `pet_packs.py` + 新 HTML | ★★ |

## 二、统计 / 数据维度增强

| 灵感 | 说明 | 落点 | 难度 |
|---|---|---|---|
| 效率分 / 专注度 | 基于番茄钟完成数 + 学习类占比 + 离开次数算每日效率分，桌宠据此变表情 | `app.py` 聚合 + `pet_engine.py` | ★★ |
| 周报 / 月报 | 数据已存 SQLite 一年（`SEGMENT_KEEP_DAYS=365`），加周期报告自动生成 + 导出图片 | `app.py` 聚合 + `dashboard.html` | ★★★ |
| 应用限额提醒 | 给某 App（游戏/短视频）设每日上限，超了桌宠跳出拦截 | `goals_util.py` + `pet_engine.py` | ★ |

## 三、分类智能化（当前痛点）

| 灵感 | 说明 | 落点 | 难度 |
|---|---|---|---|
| 浏览器网页时长加权 | 同一域名停留时长区分"刷 30 秒"与"认真看 20 分钟"，当前靠词库硬匹配易误判 | `classify.py` + `classify_words.py` | ★★ |
| 用户反馈闭环 | 桌宠问"刚才算学习还是娱乐？"点头/摇头，逐步纠偏分类规则（可学习覆盖） | `classify.py` + `pet_engine.py` | ★★★ |

## 四、AI 伴侣深化

| 灵感 | 说明 | 落点 | 难度 |
|---|---|---|---|
| 主动场景化对话 | 连续工作 90 分钟 → 建议休息；深夜刷屏 → 温柔劝睡，结合真实数据说话 | `companion.py` + `companion_ai.py` | ★★ |
| 长期记忆与连续人设 | 本地记忆文件，让 AI 记得"你这周目标总完不成""周三最容易摸鱼" | `companion_ai.py` + 新增存储 | ★★ |
| 多模态反馈 | 桌宠看截图/贴的文字后给反馈，本地跑轻量视觉模型 | `companion_ai.py` | ★★★ |

## 五、看板 / 可视化

| 灵感 | 说明 | 落点 | 难度 |
|---|---|---|---|
| 时间线拖拽标注 | 手动把某段划为"摸鱼/无效"，修正统计 | `dashboard.html` + `app.py` API | ★★ |
| 多设备数据汇总 | 多台电脑数据同步合并，看全局时长 | `app.py` + 同步层 | ★★★ |
| 主题/壁纸联动 | `data/themes` 已有主题包，桌宠+看板随白天黑夜自动换肤 | `theme_util.py` + `pet_view.py` | ★ |

## 六、工程化（长期）

| 灵感 | 说明 | 落点 | 难度 |
|---|---|---|---|
| API Key 加密存储 | `meta` 表当前明文存 `ai_api_key`，改接 Windows DPAPI 或本地密钥文件 | `app.py` 读写 meta 处 | ★ |
| 统一设置中心 | 分类规则 / 番茄钟 / 目标 / AI 参数散落各处，整合为一个设置页 | `dashboard.html` + `/api/settings` | ★★ |

---

## 推荐优先组合

**「主动场景化对话 + 应用限额提醒 + 效率分」**

- 三者都复用现有 `companion` / `goals_util` / `classify` 的数据与状态机；
- 改动集中、效果直观，能让桌宠一下有"灵魂"；
- 不需要引入新依赖或新存储，风险低。

> 下一步：选定方向后，可基于本文档逐条出具体改动方案（涉及文件、函数、数据流）。
