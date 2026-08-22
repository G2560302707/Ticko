# -*- coding: utf-8 -*-
"""内置分类词库。只放高信号词，避免单字、过短英文造成误伤。"""

def _uniq(*groups):
    seen = set()
    out = []
    for group in groups:
        for w in group:
            w = (w or "").strip()
            if not w or w in seen:
                continue
            seen.add(w)
            out.append(w)
    return tuple(out)


LEARN_SITES = (
    "雨课堂", "yuketang", "rain classroom", "rainclassroom",
    "学堂在线", "xuetangx",
    "学习通", "超星学习通", "超星尔雅", "超星慕课", "chaoxing",
    "智慧树", "zhihuishu", "知到",
    "中国大学mooc", "中国大学慕课", "icourse163", "爱课程", "icourse",
    "慕课网", "imooc.com",
    "网易云课堂", "study.163",
    "腾讯课堂", "ke.qq.com",
    "钉钉课堂", "课堂派", "ketangpai",
    "微助教", "蓝墨云班课", "蓝墨云",
    "优学院", "高校邦", "学银在线", "智慧职教", "icve.com.cn",
    "国家中小学智慧教育", "智慧教育平台", "eduyun",
    "google classroom", "classroom.google",
    "khan academy", "可汗学院",
    "coursera", "edx.org", "udemy", "udacity",
    "linkedin learning", "skillshare",
    "网易公开课", "open.163",
    "好大学在线", "cnmooc",
    "classin", "class in", "畅课",
    "希沃白板", "seewo",
    "有道精品课", "网易有道精品课",
    "新东方在线", "koolearn",
    "猿辅导", "学而思网校", "高途课堂", "高途考研",
    "作业帮直播课", "粉笔", "华图在线", "中公网校",
    "考研帮", "研招网", "chsi.com", "学信网",
    "zhihu.com", "知乎", "wikipedia", "维基百科",
    "stackoverflow", "stack overflow", "github",
    "leetcode", "力扣", "nowcoder", "牛客网",
    "csdn", "博客园", "cnblogs", "掘金", "juejin",
    "runoob", "菜鸟教程", "廖雪峰", "bilibili课堂", "哔哩哔哩课堂",
)

FUN_SITES = (
    "哔哩哔哩", "bilibili", "b23.tv",
    "youtube", "youtu.be",
    "netflix", "douyin", "抖音", "tiktok",
    "iqiyi", "爱奇艺", "youku", "优酷", "芒果tv", "mgtv",
    "腾讯视频", "v.qq.com", "西瓜视频", "快手", "kuaishou",
    "acfun", "a站", "niconico", "twitch",
)

WORK_SITES = (
    "notion", "飞书", "feishu", "钉钉", "dingtalk", "企业微信", "work.weixin",
    "docs.google", "office.com", "outlook.live", "outlook.office",
    "jira", "confluence", "腾讯文档", "石墨文档", "语雀", "figma",
    "linear.app", "tapd", "禅道", "wps云", "processon", "miro.com",
    "slack.com", "teams.microsoft", "zoom.us", "腾讯会议", "voov",
)

SOCIAL_SITES = (
    "微博", "weibo", "twitter", "x.com", "facebook", "reddit",
    "小红书", "xiaohongshu", "贴吧", "tieba", "instagram", "whatsapp",
    "知乎盐选",
)

WORK_TITLE = (
    "notion", "飞书", "feishu", "钉钉", "dingtalk", "企业微信", "work.weixin",
    "docs.google", "office.com", "outlook.live", "outlook.office", "jira",
    "confluence", "腾讯文档", "石墨文档", "语雀", "figma", "linear.app",
    "tapd", "禅道", "wps云", "腾讯会议", "teams",
)

SOCIAL_TITLE = (
    "微博", "weibo", "twitter", "x.com", "facebook", "reddit", "小红书",
    "xiaohongshu", "贴吧", "tieba", "instagram", "whatsapp",
)

FUN_TITLE = (
    "直播", "番剧", "电影", "电视剧", "综艺", "漫画", "游戏", "搞笑",
    "音乐", "短视频", "动漫", "娱乐", "mv", "鬼畜", "二创", "开箱",
    "追剧", "追番", "漫展", "偶像",
)

EXTRA_EXE = {
    "rainclassroom.exe": "学习",
    "yuketang.exe": "学习",
    "chaoxingstudy.exe": "学习",
    "chaoxing.exe": "学习",
    "zhihuishu.exe": "学习",
    "classin.exe": "学习",
    "seewo.exe": "学习",
    "youdao.exe": "学习",
    "youdaodict.exe": "学习",
    "eudic.exe": "学习",
    "anki.exe": "学习",
    "obsidian.exe": "工作",
    "typora.exe": "工作",
    "xmind.exe": "工作",
    "mindmaster.exe": "工作",
    "postman.exe": "工作",
    "navicat.exe": "工作",
    "datagrip64.exe": "工作",
    "webstorm64.exe": "工作",
    "goland64.exe": "工作",
    "clion64.exe": "工作",
    "rider64.exe": "工作",
    "androidstudio64.exe": "工作",
    "sublime_text.exe": "工作",
    "code.exe": "工作",
    "cloudmusic.exe": "娱乐",
    "qqmusic.exe": "娱乐",
    "kugou.exe": "娱乐",
    "kwmusic.exe": "娱乐",
    "spotify.exe": "娱乐",
    "bilibili.exe": "娱乐",
    "i4tools.exe": "其他",
}

LEARN_PLATFORMS = (
    "雨课堂", "学堂在线", "学习通", "超星", "智慧树", "知到",
    "中国大学MOOC", "中国大学慕课", "慕课", "MOOC", "网易云课堂",
    "腾讯课堂", "钉钉课堂", "课堂派", "微助教", "蓝墨云", "优学院",
    "高校邦", "爱课程", "学银在线", "智慧职教", "智慧教育",
    "网易公开课", "可汗学院", "Coursera", "edX", "Udemy", "ClassIn",
    "希沃", "有道精品课", "新东方在线", "猿辅导", "学而思", "高途",
    "作业帮", "粉笔公考", "华图", "中公", "考研帮", "哔哩哔哩课堂",
    "学习强国", "得到", "樊登", "网课", "公开课", "直播课", "录播课",
    "在线课堂", "线上课", "同步课", "专项课", "全程班", "冲刺班",
    "基础班", "强化班", "习题课", "答疑课", "串讲",
)

LEARN_EXAMS = (
    "考研", "考研数学", "考研英语", "考研政治", "考研专业课", "408考研",
    "统考", "初试", "复试", "考研大纲", "真题", "模拟卷", "模拟题",
    "高考", "高考数学", "高考英语", "高考物理", "高考化学", "高考生物",
    "中考", "会考", "学考", "选考", "期末", "期中", "月考", "模考",
    "四级", "六级", "四六级", "英语四级", "英语六级", "CET-4", "CET-6",
    "CET4", "CET6", "专四", "专八", "TEM-4", "TEM-8",
    "托福", "TOEFL", "雅思", "IELTS", "GRE", "GMAT", "SAT", "ACT",
    "教资", "教师资格证", "教招", "教师编制",
    "公务员", "国考", "省考", "事业单位", "事业编", "选调", "公考",
    "行测", "申论",
    "法考", "司法考试", "法律职业资格",
    "注会", "CPA", "中级会计", "初级会计", "注册会计师", "经济师",
    "一建", "一级建造师", "二建", "二级建造师", "消防工程师", "造价师",
    "软考", "软考高项", "计算机二级", "计算机三级", "NCRE",
    "专升本", "自考", "成考", "函授", "开放大学", "电大", "同等学力",
    "考研政治", "肖秀荣", "肖1000", "肖八", "肖四", "徐涛", "腿姐",
    "汤家凤", "李永乐", "张宇", "武忠祥", "蒋中挺", "王吉",
    "刘晓燕", "田静", "唐迟", "何凯文", "王江涛", "张雪峰",
    "华图教育", "中公教育", "粉笔面试", "高途考研",
)

LEARN_STEM = (
    "高数", "高等数学", "微积分", "数学分析", "线代", "线性代数",
    "概率论", "数理统计", "复变函数", "积分变换", "离散数学", "运筹学",
    "数值分析", "高等代数", "解析几何", "微分方程", "近世代数",
    "实变函数", "泛函分析",
    "大学物理", "力学", "热学", "光学", "电磁学", "量子力学",
    "电动力学", "热力学", "统计物理",
    "大学化学", "有机化学", "无机化学", "分析化学", "物理化学",
    "理论力学", "材料力学", "结构力学", "流体力学", "工程力学",
    "电工电子", "电路分析", "模拟电路", "数字电路", "信号与系统",
    "通信原理", "自动控制", "机械设计", "机械制图", "工程制图",
    "电力电子", "建筑结构", "钢筋混凝土", "土力学", "水力学",
    "工程经济学", "材料科学", "生物医学",
    "数据结构", "算法导论", "操作系统", "计算机网络", "组成原理",
    "计算机组成", "编译原理", "数据库原理", "软件工程",
    "人工智能", "机器学习", "深度学习", "神经网络", "计算机视觉",
    "自然语言处理", "嵌入式", "单片机", "数字信号处理",
    "计网", "计组", "操统", "数电", "模电", "数分", "高代",
)

LEARN_ARTS = (
    "马克思", "马原", "毛概", "史纲", "思修", "近代史纲要",
    "马克思主义", "中国近现代史", "思想道德", "形势与政策",
    "大学英语", "大学语文", "古代汉语", "现代汉语", "文学理论",
    "教育学", "心理学", "教育心理学", "普通心理学", "发展心理学",
    "西方经济学", "微观经济学", "宏观经济学", "计量经济学",
    "管理学", "会计学", "财务管理", "审计学", "统计学原理",
    "法学", "民法", "刑法", "宪法", "法理学", "行政法", "国际法",
    "民事诉讼法", "刑事诉讼法",
    "解剖学", "生理学", "病理学", "药理学", "免疫学",
    "内科学", "外科学", "护理学", "诊断学",
    "新闻学", "传播学", "社会学", "政治学", "国际关系",
)

LEARN_CS = (
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C语言",
    "C#", "Golang", "Rust语言", "Kotlin", "Swift", "PHP", "Ruby",
    "MATLAB", "SPSS", "Stata", "R语言", "HTML", "CSS",
    "Vue", "React", "Angular", "Node.js", "Django", "Flask",
    "Spring Boot", "MySQL", "Redis", "MongoDB", "Docker",
    "Kubernetes", "Linux", "Git教程", "LeetCode", "力扣",
    "剑指Offer", "蓝桥杯", "编程", "程序设计", "代码实现",
    "前端开发", "后端开发", "全栈", "爬虫", "算法题", "刷题",
    "面试题", "计算机基础", "软件设计师", "网络工程师",
    "HarmonyOS", "Android开发", "iOS开发", "Unity", "Unreal",
    "PyTorch", "TensorFlow", "Pandas", "NumPy", "SQL",
    "微信小程序", "数据分析", "数据挖掘", "大数据", "云计算",
    "网络安全", "渗透测试", "CTF", "信息安全",
)

LEARN_LANG = (
    "背单词", "单词书", "英语语法", "英语听力", "阅读理解",
    "英语写作", "英语翻译", "英语口语",     "日语", "韩语", "德语",
    "法语", "西班牙语", "俄语", "JLPT",
    "新概念英语", "赖世雄", "英语语法精讲", "听力真题",
    "口语陪练", "雅思口语", "雅思写作", "托福听力", "托福阅读",
)

LEARN_GENERIC = (
    "教程", "教学", "课程", "讲座", "讲义", "课件", "备课",
    "听课", "上课", "复习", "预习", "自习", "晚自习", "早读",
    "知识点", "考点", "精讲", "精练", "习题", "课后题", "作业讲解",
    "实验报告", "课程设计", "毕业设计", "毕业论文", "论文",
    "文献", "知网", "万方", "维普", "开题", "答辩",
    "网课回放", "录播", "答疑", "笔记", "思维导图",
    "教材", "课本", "教辅", "同步练习", "专项训练",
    "lecture", "course", "tutorial", "homework", "assignment",
    "midterm", "final exam", "textbook", "lesson", "curriculum",
    "study with me", "studywithme", "网课笔记", "考研复习",
    "高考复习", "期末复习", "期中复习", "知识点总结",
    "公开课", "名师", "板书", "推导", "证明题", "计算题",
    "选择题精讲", "大题精讲", "押题", "预测卷", "刷课",
    "学习", "自学", "补课", "辅导班", "一对一辅导",
    "知识区", "科普", "硬核科普", "学术", "科研", "实验室",
    "课题组", "seminar", "workshop", "mooc",
)

LEARN_WORDS = _uniq(
    LEARN_PLATFORMS,
    LEARN_EXAMS,
    LEARN_STEM,
    LEARN_ARTS,
    LEARN_CS,
    LEARN_LANG,
    LEARN_GENERIC,
)

EXCLUDE_LEARN = _uniq(
    (
        "搞笑", "整活", "整蛊", "鬼畜", "开箱", "吃瓜", "二创",
        "番剧", "影视剪辑", "电影解说", "电视剧解说", "综艺",
        "美食圈", "美食制作", "探店", "vlog", "Vlog",
        "美妆", "护肤", "穿搭", "发型", "化妆教程",
        "明星", "八卦", "idol", "打卡挑战",
        "游戏实况", "手游", "通关", "速通", "高光时刻",
        "原神", "星穹铁道", "绝区零", "鸣潮", "王者荣耀",
        "和平精英", "英雄联盟", "League of Legends", "LOL",
        "我的世界", "Minecraft", "第五人格", "永劫无间",
        "三角洲行动", "Valorant", "CS2", "DOTA", "吃鸡",
        "炉石传说", "阴阳师", "崩坏", "明日方舟", "原神攻略",
        "抽卡", "二游", "电竞", "赛马娘", "GTA", "塞尔达",
        "艾尔登法环", "黑神话",
    ),
)
