# -*- coding: utf-8 -*-
"""
交易很轻松 · 配置中心
=====================
所有可调参数集中在此，方便不碰代码也能改行为。
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, "web")
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")

for _d in (DATA_DIR, CACHE_DIR):
    os.makedirs(_d, exist_ok=True)

# ---------------------------------------------------------------- 网络
POLL_INTERVAL = 5           # 秒：后台抓取频率（行情 / 外围市场）
POLL_DEEP = 30              # 秒：深度分析（K线+缠论+筹码+评分）的刷新周期
HTTP_TIMEOUT = 8            # 单请求超时
HTTP_RETRY = 2              # 失败重试次数
CONCURRENCY = 6             # 并发抓取线程数
# 0.0.0.0 = 监听所有网卡，手机连同一个 WiFi 就能访问
# 只想本机用（不暴露到局域网）：设环境变量 JYHQS_HOST=127.0.0.1
SERVER_HOST = os.environ.get("JYHQS_HOST", "0.0.0.0")
LOCAL_HOST = "127.0.0.1"    # 本机浏览器打开时用这个（0.0.0.0 有些浏览器不认）
SERVER_PORT = int(os.environ.get("JYHQS_PORT", "8765"))
PORT_SCAN = 12              # 端口被占用时向后尝试的次数
AUTO_OPEN_BROWSER = True

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------- 数据长度
KLINE_LEN = 620             # 日线抓取根数（约两年半，够做长周期筹码）
KLINE_LEN_MIN = 480         # 分钟线抓取根数
US_KLINE_LEN = 620          # 美股日线（接口返回全历史，截取尾部）
FUT_KLINE_LEN = 400         # 国际期货日线

# ---------------------------------------------------------------- 外围市场
US_INDICES = [
    ("gb_$dji", "道琼斯", "US"),
    ("gb_$ixic", "纳斯达克", "US"),
    ("gb_$inx", "标普500", "US"),
]
HK_INDICES = [
    ("rt_hkHSI", "恒生指数", "HK"),
    ("rt_hkHSCEI", "国企指数", "HK"),
]
OTHER_INDICES = [
    ("int_nikkei", "日经225", "JP"),
    ("int_ftse", "英国富时", "UK"),
    ("int_dax", "德国DAX", "DE"),
]
US_STOCKS = [
    ("gb_aapl", "苹果", "US"),
    ("gb_msft", "微软", "US"),
    ("gb_nvda", "英伟达", "US"),
    ("gb_goog", "谷歌", "US"),
    ("gb_amzn", "亚马逊", "US"),
    ("gb_tsla", "特斯拉", "US"),
    ("gb_meta", "Meta", "US"),
]
HK_STOCKS = [
    ("hk00700", "腾讯控股", "HK"),
    ("hk09988", "阿里巴巴", "HK"),
    ("hk03690", "美团", "HK"),
    ("hk01810", "小米集团", "HK"),
    ("hk09618", "京东集团", "HK"),
]
FX_LIST = [
    ("fx_susdcny", "美元/人民币", "FX"),
    ("fx_seurusd", "欧元/美元", "FX"),
    ("fx_susdjpy", "美元/日元", "FX"),
    ("fx_sgbpusd", "英镑/美元", "FX"),
    ("fx_saudusd", "澳元/美元", "FX"),
]
COMMODITY_LIST = [
    ("hf_GC", "纽约黄金", "CM"),
    ("hf_SI", "纽约白银", "CM"),
    ("hf_CL", "纽约原油", "CM"),
    ("hf_CAD", "伦铜", "CM"),
    ("nf_AU0", "沪金连续", "CM"),
    ("nf_RB0", "螺纹钢连续", "CM"),
]
GLOBAL_ALL = (US_INDICES + HK_INDICES + OTHER_INDICES + US_STOCKS +
              HK_STOCKS + FX_LIST + COMMODITY_LIST)

# 外围代码区分大小写（hf_GC / rt_hkHSI），用小写别名做归一化
GLOBAL_ALIAS = {k.lower(): k for k, _, _ in GLOBAL_ALL}

# 外围标的的 K 线来源
US_KLINE_MAP = {"gb_$dji": ".DJI", "gb_$ixic": ".IXIC", "gb_$inx": ".INX"}
FUT_KLINE_MAP = {"hf_GC": "GC", "hf_SI": "SI", "hf_CL": "CL", "hf_CAD": "CAD"}

# ---------------------------------------------------------------- 基金
# 基准指数：名称关键字 -> 新浪指数代码（**顺序即优先级，具体的放前面**）
BENCHMARKS = [
    # --- 行业主题（先匹配，避免「中证白酒」被「中证」吃掉）
    ("主要消费", "sh000932"),
    ("白酒", "sz399997"),
    ("证券公司", "sz399975"),
    ("证券指数", "sz399975"),
    ("医疗", "sz399989"),
    ("医药", "sz399989"),
    ("生物", "sz399989"),
    ("银行", "sz399986"),
    ("军工", "sz399967"),
    ("新能源车", "sz399976"),
    ("新能源汽车", "sz399976"),
    ("光伏", "sz399976"),
    ("半导体", "sz399995"),
    ("芯片", "sz399995"),
    ("消费", "sh000932"),
    ("红利", "sh000015"),
    ("价值", "sh000922"),
    # --- 宽基
    ("沪深300", "sh000300"),
    ("中证500", "sh000905"),
    ("中证1000", "sh000852"),
    ("上证50", "sh000016"),
    ("创业板", "sz399006"),
    ("科创50", "sh000688"),
    ("科创", "sh000688"),
    ("恒生", "rt_hkHSI"),
    ("纳斯达克", "gb_$ixic"),
    ("标普", "gb_$inx"),
    ("黄金", "hf_GC"),
]
DEFAULT_BENCHMARK = "sh000300"

FUND_RF_RATE = 0.018        # 无风险利率（年化），用于夏普比率

# 场外基金种子池 —— 新浪没有「场外基金列表」接口，这里用实测有效的常见基金
# （全部逐个调 f_ 净值接口验证过，名称由接口实时返回，不写死）
OFUND_SEED = [
    # 宽基指数
    "000961", "000008", "110020", "001548", "001549", "003765",
    # 行业主题（被动）
    "161725", "012414", "001595", "001594", "001631", "001632",
    "001618", "000248", "161028", "501057", "001630", "002611",
    "000216", "000217", "003765", "110003",
    # 主动权益
    "110022", "000001", "000011", "519066", "001938", "005827",
    "003096", "001717", "000083", "260108", "163406", "519674",
    "001102", "002190", "001186", "519005", "001410", "001714",
    "001705", "163402", "519068", "270002", "050001", "002340",
    "002851", "001837", "001838", "110011",
]

# ---------------------------------------------------------------- 指标参数
MA_PERIODS = (5, 10, 20, 60, 120)
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
RSI_PERIOD = 14
KDJ_N, KDJ_M1, KDJ_M2 = 9, 3, 3
BOLL_N, BOLL_K = 20, 2.0
ATR_PERIOD = 14
ADX_PERIOD = 14
CCI_PERIOD = 20
WR_PERIOD = 14
MFI_PERIOD = 14
OBV_MA = 30

# ---------------------------------------------------------------- 缠论
CHAN_MIN_GAP = 4            # 笔：两分型之间合并K线的最小间隔（老笔标准）
CHAN_BI_MIN_BARS = 5        # 一笔至少覆盖的原始K线数
CHAN_ZHONGSHU_MIN = 3       # 中枢至少三笔
CHAN_DIVERGENCE_RATIO = 1.25  # 背驰：前段 MACD 面积 / 后段 的比值阈值

# ---------------------------------------------------------------- 筹码 (CYQ)
CHIP_BINS = 220             # 价格分档数
CHIP_DECAY_K = 1.0          # 换手衰减系数（越大历史筹码消失越快）
CHIP_MAX_DAYS = 480         # 参与计算的最大交易日数
CHIP_MAIN_PEAK_COVER = 0.60  # 主力集中区：从峰值向两侧扩展到累计 60%
CHIP_FLOAT_FALLBACK = 1e9   # 拿不到流通股本时的兜底（退化为按成交量相对值计算）

# ---------------------------------------------------------------- 评分权重
SCORE_WEIGHTS = {
    "trend": 1.25,
    "momentum": 1.05,
    "volume": 0.95,
    "chip": 1.15,
    "chan": 1.10,
    "pattern": 0.70,
    "risk": 0.60,
}

# ---------------------------------------------------------------- 日志
LOG_ANALYSIS = True
LOG_COLOR = True


def enable_utf8_console():
    """Windows 控制台切 UTF-8，避免中文乱码。"""
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
