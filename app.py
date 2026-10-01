#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出海合规罗盘 ExportCompass · 二轮车出口合规雷达 + 落地成本测算
输入：目标市场 + 车型动力类型 + FOB价/数量/运输方式 → 输出：合规要求差距清单 + CBU/SKD/CKD 落地成本区间 + AI 问询清单
认证要求数据锚定 2025-2026 公开信源（欧盟168/2013、美国DOT/EPA、沙特SABER、阿联酋ECAS、印尼TKDN、肯尼亚KEBS、尼日利亚SONCAP、巴西INMETRO），禁 Mock。
"""
import json
import math
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
OUT_DIR = os.path.join(BASE, "output")
STATIC = os.path.join(BASE, "static")
for d in (DATA_DIR, OUT_DIR, STATIC):
    os.makedirs(d, exist_ok=True)

# ---------------- 认证要求数据库（全部锚定公开信源） ----------------
# req: [名称, 主管机构, 要点, 周期(周), 类型 ice/ev/both]
MARKETS = {
    "eu": {
        "name": "欧盟 EU", "flag": "🇪🇺", "tier": "高端市场",
        "duty": {"cbu": (0.10, 0.16), "skd": (0.06, 0.10), "ckd": (0.03, 0.06)},
        "duty_note": "基础关税+（电自/电摩双反税另计，区间化幅度，按品类裁定）",
        "reqs": [
            ["整车型式核准 WVTA", "欧盟成员国核准机构（TÜV/IDIADA/VCA等）",
             "Regulation (EU) No 168/2013：L3e 摩托车整车型式核准，50+ 项零部件 E-Mark（ECE R78 制动/ABS、R41 噪声、R10 电磁兼容、防盗等），凭 COC 一致性证书方可 27 国上牌", 40, "both"],
            ["排放 Euro 5+", "欧盟委员会",
             "高压闭环 EFI 电喷（λ=1.00±0.02）、三元催化，CO≤1.0g/km / HC≤0.10g/km / NOx≤0.06g/km，标配 ISO 14229 / CAN-bus OBD-II 故障监控", 16, "ice"],
            ["欧盟《电池法规》合规", "欧盟委员会",
             "2025 年生效：电池护照/碳足迹披露/回收料比例/标识与信息披露，不满足直接影响通关与在欧销售", 12, "ev"],
            ["CE + 电池安全", "公告机构 Notified Body",
             "充电器/电池/电气系统 CE，LVD+EMC 指令，锂电池 UN38.3 运输测试", 8, "ev"],
        ],
        "ai_questions": [
            "列出 Regulation (EU) 168/2013 下我的车型（L3e 类）申请 WVTA 需要的 E-Mark 零部件子项清单，哪些可以沿用供应商已有证书？",
            "2025 欧盟《电池法规》电池护照对我的电池包要求哪些碳足迹/再生料披露？准备材料清单和时间表？",
            "我的车型出口欧盟，CBU 整车与 CKD 散件两种模式下的关税与双反税如何计算？哪种综合成本更低？",
        ],
    },
    "us": {
        "name": "美国 US", "flag": "🇺🇸", "tier": "高端市场",
        "duty": {"cbu": (0.45, 0.55), "skd": (0.35, 0.45), "ckd": (0.25, 0.40)},
        "duty_note": "对中国原产电动两轮车总进口税率约45%（基础+301+互惠叠加），钢铝附加税清单暂未覆盖两轮车主体",
        "reqs": [
            ["DOT 联邦机动车安全标准", "美国交通部 NHTSA",
             "FMVSS：灯具、轮胎、刹车软管等通过 DOT 认证，自我认证+NHTSA 市场抽查", 12, "both"],
            ["EPA 排放认证", "美国环保署",
             "发动机/电驱系统 EPA 排放合格证；加州市场另需 CARB 备案", 16, "both"],
            ["CPSC 锂电池安全", "消费者产品安全委员会",
             "电动两轮车电气系统安全标准、锂电池安全标准认证；含锂电池进口触及危险品运输申报要求", 8, "ev"],
            ["海关归类预裁定", "美国海关 CBP",
             "HTSUS 8711.60 子目归类决定基础关税与附加关税适用性，归类错误=清关风险", 6, "both"],
        ],
        "ai_questions": [
            "HTSUS 8711.60 下我的车型（电摩/燃油/功率参数）应归入哪个子目？如何向 CBP 申请归类预裁定？",
            "我的锂电池包出口美国，CPSC 新规+UN38.3+危险品运输申报要准备哪些文件？",
            "美国 45% 复合关税下，走 CKD 或经第三国组装的合规路径有哪些？各自的真实风险？",
        ],
    },
    "sea_id": {
        "name": "印度尼西亚", "flag": "🇮🇩", "tier": "量大新兴",
        "duty": {"cbu": (0.35, 0.60), "skd": (0.15, 0.25), "ckd": (0.05, 0.10)},
        "duty_note": "东南亚代表市场：CBU 高关税 35-60%，CKD 散件 5-10% 且综合成本降约 30%",
        "reqs": [
            ["TKDN 本地化率认证", "印尼工业部",
             "电动摩托与零部件须获 TKDN 认证（本地化比例审核）才能进入市场准入、补贴与税费优惠；2026 年起进口激励大幅缩减，须本地建厂或合作组装", 12, "ev"],
            ["进口配额与许可", "印尼贸易部",
             "2025-09 政策信号：依赖进口的电动车产品（含电摩）自 2026 年起大幅缩减进口激励，通道收紧", 8, "both"],
        ],
        "ai_questions": [
            "TKDN 认证的审核材料、本地化率计算口径是什么？CKD 组装能达到多少 TKDN 比例？",
            "印尼 2026 年缩减进口激励后，哪些车型品类还允许 CBU 进口？补贴目录怎么进？",
        ],
    },
    "mena_ksa": {
        "name": "沙特阿拉伯", "flag": "🇸🇦", "tier": "中东认证型",
        "duty": {"cbu": (0.05, 0.15), "skd": (0.03, 0.08), "ckd": (0.00, 0.05)},
        "duty_note": "GCC 关税同盟基准税率较低，但认证门槛极高",
        "reqs": [
            ["SABER 平台强制认证", "沙特标准局 SASO",
             "摩托类与个人移动设备须取得技术法规下的型号认证 P-CoC / 装运批次认证 S-CoC，无 SABER 凭证海关不放行", 10, "both"],
            ["锂电池专项要求", "SASO",
             "锂电池市场准入、运输与标签的具体文件 + 温控和运输证明", 6, "ev"],
            ["50℃ 极热工况验证", "SASO/技术机构",
             "GCC G-Mark：50℃ 极热荒漠工况耐受性验证", 8, "both"],
        ],
        "ai_questions": [
            "SABER 平台申请 P-CoC/S-CoC 的完整流程、所需技术文档和周期？",
            "沙特锂电池温控运输证明的出具机构与测试项目有哪些？",
        ],
    },
    "mena_ae": {
        "name": "阿联酋 UAE", "flag": "🇦🇪", "tier": "中东认证型",
        "duty": {"cbu": (0.05, 0.10), "skd": (0.03, 0.06), "ckd": (0.00, 0.05)},
        "duty_note": "GCC 关税同盟，认证为主门槛",
        "reqs": [
            ["ECAS 强制认证", "阿联酋标准计量局 ESMA",
             "受管制的电动两轮车与电池、充电器等电气部件须在 ECAS 规则下注册并取得合格证书与声明；未登记或证书不全=滞港或退运", 8, "both"],
            ["阿拉伯语标签审查", "ESMA",
             "标签须含阿拉伯语信息并符合标签审查要求", 4, "both"],
        ],
        "ai_questions": [
            "ECAS 注册对电摩整车+电池+充电器的拆分申请策略？证书有效期与更新节奏？",
            "阿拉伯语标签的强制字段清单与字体规范？",
        ],
    },
    "afr_ke": {
        "name": "肯尼亚 Kenya", "flag": "🇰🇪", "tier": "非洲增量",
        "duty": {"cbu": (0.35, 0.60), "skd": (0.15, 0.25), "ckd": (0.05, 0.10)},
        "duty_note": "东非共同体共同对外关税 + PVoC 费用",
        "reqs": [
            ["KEBS PVoC 出口国检验", "肯尼亚标准局 KEBS",
             "电动两轮车与电池实施货物合格性核查：出口国装运前检验并取得检测合格证明，否则通关被拒或本地抽样检验自担费用", 6, "both"],
        ],
        "ai_questions": [
            "KEBS PVoC 在中国境内的授权检验机构有哪些？装运前检验预约周期？",
        ],
    },
    "afr_ng": {
        "name": "尼日利亚 Nigeria", "flag": "🇳🇬", "tier": "非洲增量",
        "duty": {"cbu": (0.35, 0.60), "skd": (0.15, 0.25), "ckd": (0.05, 0.10)},
        "duty_note": "西非高关税市场，CKD 本地组装为主流打法",
        "reqs": [
            ["SONCAP 清关认证", "尼日利亚标准组织 SON",
             "PC（产品证书）+ SC（装运证书）双证清关，缺证滞港", 6, "both"],
        ],
        "ai_questions": [
            "SONCAP 的 PC 证分几种模式？首次申请与续期的差异？",
        ],
    },
    "latam_br": {
        "name": "巴西 Brazil", "flag": "🇧🇷", "tier": "拉美核心",
        "duty": {"cbu": (0.35, 0.60), "skd": (0.20, 0.35), "ckd": (0.05, 0.15)},
        "duty_note": "南美最高关税壁垒之一，玛瑙斯自贸区 CKD 配额是主流路径",
        "reqs": [
            ["INMETRO 强制认证", "巴西计量标准化质量院 INMETRO",
             "PROMOT M5 排放标准 + 零部件强制 INMETRO 认证", 16, "both"],
            ["玛瑙斯自贸区 CKD 配额", "巴西发展工业外贸部",
             "Manaus 自贸区 CKD 组装配额申请，享关税减免", 20, "both"],
        ],
        "ai_questions": [
            "INMETRO 认证对摩托零部件的强制清单与本地代表（representante legal）要求？",
            "玛瑙斯自贸区 CKD 配额近年发放节奏与申请材料？",
        ],
    },
}

MODES = {
    "cbu": {"name": "CBU 整车出口", "units_per_ctn": (40, 50),
            "desc": "成品装木箱/铁架 · 关税最高 · 适合关税低或无组装能力市场"},
    "skd": {"name": "SKD 半散件", "units_per_ctn": (70, 90),
            "desc": "拆前轮/车把/前减震/尾箱 · 需海外基础拧紧工位与下线检测"},
    "ckd": {"name": "CKD 全散件", "units_per_ctn": (140, 160),
            "desc": "8大系统100%零部件分箱 · 关税最低 · 需海外组装厂与工艺SOP输出"},
}
VEH_TYPES = {"ice": "燃油摩托", "ev": "电动摩托"}


def build_matrix(market_key, veh):
    m = MARKETS.get(market_key)
    if not m:
        return None
    reqs = [r for r in m["reqs"] if r[4] in ("both", veh)]
    total_weeks = max(r[3] for r in reqs) if reqs else 0
    return {"market": m["name"], "flag": m["flag"], "tier": m["tier"],
            "veh": VEH_TYPES.get(veh, veh), "reqs": reqs,
            "total_weeks": total_weeks,
            "duty_note": m["duty_note"], "ai_questions": m["ai_questions"]}


def calc_landed(market_key, mode_key, fob, qty, container_cost):
    m = MARKETS.get(market_key)
    md = MODES.get(mode_key)
    if not m or not md or fob <= 0 or qty <= 0:
        return None
    lo, hi = m["duty"][mode_key]
    up_lo, up_hi = md["units_per_ctn"]
    ctns = math.ceil(qty / up_hi)      # 按高装载密度估柜数（保守运费）
    freight_unit = container_cost / ((up_lo + up_hi) / 2.0)
    res = {
        "mode": md["name"], "mode_desc": md["desc"],
        "qty": qty, "fob": fob, "ctns": ctns,
        "duty_lo": round(lo * 100, 1), "duty_hi": round(hi * 100, 1),
        "freight_unit": round(freight_unit, 1),
        "landed_lo": round(fob * (1 + lo) + freight_unit, 0),
        "landed_hi": round(fob * (1 + hi) + freight_unit, 0),
    }
    # 与 CBU 对比
    if mode_key != "cbu":
        clo, chi = m["duty"]["cbu"]
        base_lo = fob * (1 + clo) + container_cost / ((MODES["cbu"]["units_per_ctn"][0] + MODES["cbu"]["units_per_ctn"][1]) / 2.0)
        base_hi = fob * (1 + chi) + container_cost / ((MODES["cbu"]["units_per_ctn"][0] + MODES["cbu"]["units_per_ctn"][1]) / 2.0)
        res["vs_cbu_save_unit"] = round((base_lo + base_hi) / 2 - (res["landed_lo"] + res["landed_hi"]) / 2, 0)
        res["vs_cbu_save_pct"] = round(res["vs_cbu_save_unit"] / ((base_lo + base_hi) / 2) * 100, 1)
    else:
        res["vs_cbu_save_unit"] = 0
        res["vs_cbu_save_pct"] = 0.0
    return res


def render_report(matrix, cost, params):
    L = []
    L.append("# %s %s · 出海合规差距报告" % (matrix["flag"], matrix["market"]))
    L.append("")
    L.append("> 车型：%s　运输模式：%s　数量：%s 台" % (matrix["veh"], cost["mode"], cost["qty"]))
    L.append("- **生成日期**：%s" % time.strftime("%Y-%m-%d"))
    L.append("- **合规最短板**：并行推进下仍需约 **%s 周**（最长单项决定整车上市时间）" % matrix["total_weeks"])
    L.append("")
    L.append("## 合规要求清单（缺一不可）")
    L.append("")
    L.append("| 认证/要求 | 主管机构 | 要点 | 周期(周) |")
    L.append("|---|---|---|---|")
    for r in matrix["reqs"]:
        L.append("| %s | %s | %s | %s |" % (r[0], r[1], r[2], r[3]))
    L.append("")
    L.append("## 落地成本测算（%s）" % cost["mode"])
    L.append("")
    L.append("- FOB 单价：$%s × %s 台" % (cost["fob"], cost["qty"]))
    L.append("- 关税区间：%s%% ~ %s%%（%s）" % (cost["duty_lo"], cost["duty_hi"], matrix["duty_note"]))
    L.append("- 预计用柜：%s 柜 · 单台海运分摊 ≈ $%s" % (cost["ctns"], cost["freight_unit"]))
    L.append("- **单台落地成本区间：$%s ~ $%s**" % (cost["landed_lo"], cost["landed_hi"]))
    if cost["vs_cbu_save_pct"]:
        L.append("- 对比 CBU 整车模式：**每台约省 $%s（-%s%%）**" % (cost["vs_cbu_save_unit"], cost["vs_cbu_save_pct"]))
    L.append("")
    L.append("## 问 AI 的合规问题清单")
    for i, q in enumerate(matrix["ai_questions"], 1):
        L.append("%d. %s" % (i, q))
    L.append("")
    L.append("---")
    L.append("*出海合规罗盘 ExportCompass · 认证要求数据锚定2025-2026公开信源，具体以认证机构与目标国官方最新公告为准*")
    return "\n".join(L)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
                return self._send(200, f.read())
        if path == "/api/meta":
            return self._send(200, json.dumps({
                "markets": {k: {"name": v["name"], "flag": v["flag"], "tier": v["tier"],
                                "req_count": len(v["reqs"])} for k, v in MARKETS.items()},
                "modes": {k: {"name": v["name"], "desc": v["desc"],
                              "units": "%d-%d台/柜" % v["units_per_ctn"]} for k, v in MODES.items()},
                "veh": VEH_TYPES,
            }, ensure_ascii=False), "application/json; charset=utf-8")
        m = re.match(r"^/download/([0-9a-f-]{36})\.md$", path)
        if m:
            fp = os.path.join(OUT_DIR, m.group(1) + ".md")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), "text/markdown; charset=utf-8",
                                      {"Content-Disposition": "attachment; filename=compass.md"})
        return self._send(404, "not found", "text/plain")

    def do_POST(self):
        if urlparse(self.path).path != "/api/analyze":
            return self._send(404, "not found", "text/plain")
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            mk = data.get("market", "")
            if mk not in MARKETS:
                return self._send(400, json.dumps({"ok": False, "error": "market 无效"}),
                                  "application/json; charset=utf-8")
            veh = data.get("veh", "ice")
            mode = data.get("mode", "cbu")
            if veh not in VEH_TYPES or mode not in MODES:
                return self._send(400, json.dumps({"ok": False, "error": "veh/mode 无效"}),
                                  "application/json; charset=utf-8")
            fob = float(data.get("fob") or 0)
            qty = int(data.get("qty") or 0)
            ctn = float(data.get("container_cost") or 3000)
            matrix = build_matrix(mk, veh)
            cost = calc_landed(mk, mode, fob, qty, ctn)
            if not matrix or not cost:
                return self._send(400, json.dumps({"ok": False, "error": "参数无效"}),
                                  "application/json; charset=utf-8")
            pid = str(uuid.uuid4())
            report = render_report(matrix, cost, data)
            with open(os.path.join(OUT_DIR, pid + ".md"), "w", encoding="utf-8") as f:
                f.write(report)
            with open(os.path.join(DATA_DIR, pid + ".json"), "w", encoding="utf-8") as f:
                json.dump({"id": pid, "created": time.strftime("%Y-%m-%d"),
                           "input": data, "matrix": matrix, "cost": cost},
                          f, ensure_ascii=False, indent=1)
            return self._send(200, json.dumps({"ok": True, "id": pid, "matrix": matrix,
                                               "cost": cost, "report": report,
                                               "download": "/download/%s.md" % pid},
                                              ensure_ascii=False),
                              "application/json; charset=utf-8")
        except Exception as e:
            return self._send(500, json.dumps({"ok": False, "error": str(e)}),
                              "application/json; charset=utf-8")


if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", "8681"))
    print("ExportCompass running at http://127.0.0.1:%d" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
