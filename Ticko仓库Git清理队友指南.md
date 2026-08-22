# Ticko 仓库 Git 合并冲突清理指南（队友执行版）

> 用途：把"每台机器/每次运行都会变"的文件移出版本控制，根除多人协作时的合并冲突。
> 适用范围：本仓库（Ticko）。执行前请先备份或确保手头改动已提交/暂存。

---

## 一、为什么要做这件事（冲突根因）

仓库频繁冲突，**不是代码问题，而是一批"机器/运行相关"的文件被纳入了版本控制**：

1. **2568 个 `.pyc` 字节码缓存**（`python/Lib/__pycache__/` 和 `app/__pycache__/`）。每次运行程序就重写，内容随机器、随 Python 版本不同而不同 → 改代码跑一下再提交就"被修改" → 一合并必冲突。
2. **`data/` 下的运行时/用户数据**：`usage.db`（每 3 秒在写）、`app_icons/*.png`（运行时抓窗口图标）、`themes/`、`pets/`、`sounds/`、`*.pid`、`*.lock`、`app.log` → 每台机器都不一样 → 必冲突。
3. **隐藏元凶：`.gitignore` 本身是 UTF-16 编码**。git 把它当二进制，里面写的忽略规则**全部没生效**——这就是之前反复加规则、反复还在冲突的根源。

---

## 二、⚠️ 两个必踩的坑（重点看）

### 坑 1：`.gitignore` 必须是 UTF-8 无 BOM
如果是 UTF-16（用某些编辑器/echo 写容易带），git 无法解析，所有规则失效。先确认：

```bash
head -c 16 .gitignore | od -An -tx1
# 正常：纯 ASCII（如 23 20 64 61 ...），每个字节后没有 00
# 异常：23 00 20 00 ...（每个字符后跟 00）= UTF-16，必须重写
```

重写请用 Python（别用 echo/记事本，容易又写成 UTF-16 或带 BOM）：

```bash
python/python.exe - <<'PY'
lines = [
    "# runtime data / state files",
    "data/*.log",
    "data/*.db",
    "data/*.db-wal",
    "data/*.db-shm",
    "data/*.pid",
    "data/*.lock",
    "data/instance.lock",
    "data/app.pid",
    "data/app_icons/",
    "data/url.txt",
    "data/shortcut_done",
    "",
    "# user runtime data (custom themes/pets/sounds/previews)",
    "data/pets/",
    "data/themes/",
    "data/sounds/",
    "data/voice_samples/",
    "",
    "# python bytecode cache",
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "",
    "# editor / os",
    ".DS_Store",
    "*.swp",
    "",
    "# workbuddy local tool data (machine-specific)",
    ".workbuddy/",
    "",
    "# one-off local helper scripts",
    "voice_preview.py",
    "edge_preview.py",
]
with open(".gitignore", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("written")
PY
```

> 提醒：如果你们和我的分支处理范围不同（比如想保留 `themes`/`sounds` 当内置资源），按需删掉上面对应几行再写。

### 坑 2：Windows 下 `git rm --pathspec-from-file` 用 CRLF 列表会静默失败
如果把 `git ls-files` 的输出存成文件再喂给 `--pathspec-from-file`，Git Bash / Windows 会写成 **CRLF 行尾**，git 把每行当成"带 `\r` 的文件名"，匹配不到，而且**不报错**——你以为删了 2568 个 pyc，其实索引里一个没少。
✅ 正确做法：用 Python 写 **LF 行尾**的列表文件，并加 `--ignore-unmatch`（对不存在的 pathspec 不报错）。

---

## 三、执行步骤（复制即用，在仓库根目录的 Git Bash 里跑）

```bash
cd /d/个人项目/电脑使用时长统计/Ticko

# 步骤1：先用上方"坑1"代码重写 .gitignore 为 UTF-8，确认输出无 00 字节

# 步骤2：从索引移除 data 运行时/用户数据 和 .workbuddy（本地文件保留不删）
git rm --cached -r --ignore-unmatch -q -- \
  data/app_icons data/pets data/themes data/sounds \
  data/url.txt data/shortcut_done data/instance.lock \
  data/app.pid data/usage.db data/usage.db-wal data/usage.db-shm data/app.log
git rm --cached -r --ignore-unmatch -q -- .workbuddy

# 步骤3：用 Python 生成 LF 行尾列表，移除全部 .pyc（关键，避开坑2）
python/python.exe - <<'PY'
import subprocess
out = subprocess.check_output(["git","ls-files","--","*.pyc"]).decode("utf-8").splitlines()
print("pyc in index:", len(out))
with open("pyc_list.txt","w",newline="\n",encoding="utf-8") as f:
    f.write("\n".join(out)+"\n")
PY
git rm --cached --ignore-unmatch --pathspec-from-file=pyc_list.txt -q
rm -f pyc_list.txt
```

---

## 四、提交

```bash
git add .gitignore
git commit -m "chore: 将运行时数据与缓存产物移出版本控制以消除合并冲突
- 重写 .gitignore 为 UTF-8（修复此前 UTF-16 导致规则失效）
- git rm --cached 移除已追踪的 .pyc 字节码缓存及 .workbuddy 本地数据（本地文件保留）"
```

---

## 五、验证（务必做，别跳过）

```bash
# 索引里不应再有 pyc（应为 0）
git ls-files | grep -c '\.pyc$'

# data / .workbuddy 不应再被追踪（应为空）
git ls-files data
git ls-files .workbuddy

# 本地文件是否还在（应存在，程序照常运行）
ls data/usage.db python/Lib/__pycache__/ 2>&1 | head

# .gitignore 规则是否真生效（git add -n 仅 dry-run，不会真加）
git add -n data/usage.db        # 应提示 would not be added / ignored
```

---

## 六、副作用提醒（推送给全队前务必看）

- `git rm --cached` **只删索引、不删本地文件**，所以你本机 `data/`、`python/`、提醒音都完好，程序照常跑。
- 但**队友 pull 这个提交后，他们本地原本被追踪的 `data/*` 会被 git 删除**：
  - `data/sounds/builtin/*.wav`（程序内置提醒音）会被删 → 提醒音静默失效（代码有 fallback，不崩）。
  - 他们的本地自定义 `themes/`、`pets/` 也会被清掉（属个人数据，影响有限，程序会重新生成）。
- 如需保护提醒音：在 `.gitignore` 里加 `!data/sounds/builtin/` 例外，并用 `git add` 重新纳入版本控制。
- 推送后请**通知所有队友 pull 一次**，让他们的仓库也解除追踪，否则他们下次提交又会把这些文件加回来、冲突重演。

---

## 七、转发给队友的一句话

> 先把手头改动提交或 `git stash`，然后 pull 我这个清理提交；pull 后如果 `data/sounds/builtin/` 被删且你需要提醒音，从别人那拷一份或重装资源即可。之后改代码、跑程序，不会再因为这些缓存/数据文件产生合并冲突了。
