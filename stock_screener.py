#!/usr/bin/env python3
"""
A股涨停股策略筛选脚本
按「北京炒家」首板战法 +「陈小群」龙头战法 自动筛选

运行时机: 每个交易日 16:00 (盘后数据已更新)
数据源: 新浪财经 API
"""

import urllib.request
import json
import re
from datetime import datetime, time

# ── 配置 ──────────────────────────────────────────
SINA_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://finance.sina.com.cn/'
}

# 北京炒家筛选条件
BJ_MIN_NMC = 20    # 流通市值下限 (亿)
BJ_MAX_NMC = 100   # 流通市值上限 (亿)
BJ_MAX_PRICE = 20  # 股价上限 (元)
BJ_MIN_PCT = 9.5   # 最低涨幅 (%)

# ── 数据获取 ──────────────────────────────────────
def fetch_page(page):
    """获取新浪财经涨幅榜一页数据"""
    url = (
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "Market_Center.getHQNodeData"
        f"?page={page}&num=80&sort=changepercent&asc=0"
        "&node=hs_a&symbol=&_s_r_a=auto"
    )
    req = urllib.request.Request(url, headers=SINA_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode('gbk', errors='ignore')
            return json.loads(raw)
    except Exception as e:
        return []


def get_all_limit_up_stocks():
    """获取所有涨停的主板股票"""
    all_stocks = []
    seen_pct_below_threshold = False

    for page in range(1, 60):
        data = fetch_page(page)
        if not data:
            break

        for s in data:
            sym = s.get('symbol', '')
            code = sym[2:] if len(sym) > 2 else sym  # 去掉 sz/sh/bj 前缀

            # 只看主板 (60xxxx 上海, 00xxxx 深圳)
            if not (code.startswith('60') or code.startswith('00')):
                continue

            pct = float(s.get('changepercent', 0))
            if pct < BJ_MIN_PCT:
                seen_pct_below_threshold = True
                continue

            nmc = float(s.get('nmc', 0)) / 10000  # 万元 → 亿元
            price = float(s.get('trade', 0))
            turnover = float(s.get('turnoverratio', 0))
            mktcap = float(s.get('mktcap', 0)) / 10000
            volume = float(s.get('volume', 0))
            amount = float(s.get('amount', 0))

            all_stocks.append({
                'code': code,
                'name': s.get('name', ''),
                'price': price,
                'pct': pct,
                'nmc_yi': nmc,
                'mktcap_yi': mktcap,
                'turnover': turnover,
                'pe': s.get('per', ''),
                'volume': volume,
                'amount': amount,
            })

        # 如果这一页已经有低于阈值的且已经翻过几页，停止
        if seen_pct_below_threshold and page > 5:
            break

    return all_stocks


# ── 概念归类（基于股票名称/代码的启发式判断）─────────
def guess_concept(name, code):
    """根据股票名称推断所属概念板块"""
    name = str(name)
    
    concepts = []
    
    # 医药/医疗类 (including TCM and pharma)
    pharma_keywords = ['医药', '药业', '制药', '药', '生物', '医疗', '基因', '蛋白', '细胞',
                       '三联', '珍宝岛', '誉衡', '海正', '哈药', '开开', '普洛', '瑞康',
                       '冀衡', '华兰']
    if any(kw in name for kw in pharma_keywords):
        concepts.append('医药')
    
    # CRO/CDMO
    cro_names = ['药石', '凯莱英', '博腾', '昭衍', '皓元', '毕得', '奥浦迈', 
                 '诺唯赞', '近岸', '百普赛斯', '义翘', '南模', '百花']
    if any(kw in name for kw in cro_names):
        concepts.append('CXO/CRO')
    
    # 婴童/纺织
    baby_names = ['金发拉比', '拉比']
    if any(kw in name for kw in baby_names):
        concepts.append('婴童概念')
    
    # 石墨烯/新材料
    graphene_names = ['德尔未来', '德尔']
    if any(kw in name for kw in graphene_names):
        concepts.append('石墨烯')
    
    # 半导体/电子/新材料
    semi_keywords = ['电子', '新材', '光电', '芯片', '半导体', '微', '硅', '锗', '稀土']
    if any(kw in name for kw in semi_keywords):
        concepts.append('新材料/电子')
    
    # 通信/5G
    comm_keywords = ['通信', '凡谷', '通宇', '光迅', '天线']
    if any(kw in name for kw in comm_keywords):
        concepts.append('通信/5G')
    
    # PCB
    pcb_names = ['博敏', '依顿', '奥士康', '景旺', '华正', '生益']
    if any(kw in name for kw in pcb_names):
        concepts.append('PCB')
    
    # 基建
    infra_keywords = ['建材', '管道', '爆破', '保利', '民爆']
    if any(kw in name for kw in infra_keywords):
        concepts.append('基建')
    
    # 汽车
    auto_keywords = ['汽车', '秦安', '朗特']
    if any(kw in name for kw in auto_keywords):
        concepts.append('汽车零部件')
    
    # 稀土/有色
    metal_keywords = ['稀土', '锗业', '有研', '盛达']
    if any(kw in name for kw in metal_keywords):
        concepts.append('有色金属')
    
    if not concepts:
        concepts.append('其他')
    
    return concepts


# ── 分析函数 ──────────────────────────────────────
def apply_beijing_strategy(stocks):
    """北京炒家：首板打板策略筛选"""
    results = []
    for s in stocks:
        score = 0
        reasons = []
        flags = []
        
        # 1. 流通市值 20-100亿
        if BJ_MIN_NMC <= s['nmc_yi'] <= 100:
            score += 2
            reasons.append(f"流通市值{s['nmc_yi']:.1f}亿 ✅")
            flags.append('✅市值')
        elif s['nmc_yi'] <= 200:
            reasons.append(f"流通市值{s['nmc_yi']:.1f}亿 ⚠️(偏大)")
            flags.append('⚠️市值')
        else:
            reasons.append(f"流通市值{s['nmc_yi']:.1f}亿 ❌(过大)")
            flags.append('❌市值')
        
        # 2. 股价 < 20
        if s['price'] < 20:
            score += 2
            reasons.append(f"股价 ¥{s['price']:.2f} ✅")
            flags.append('✅股价')
        else:
            reasons.append(f"股价 ¥{s['price']:.2f} ❌(>20)")
            flags.append('❌股价')
        
        # 3. 换手率适中 (2%-25%)
        if 2 <= s['turnover'] <= 25:
            score += 1
            reasons.append(f"换手率 {s['turnover']:.1f}% ✅(活跃)")
        elif s['turnover'] < 2:
            reasons.append(f"换手率 {s['turnover']:.1f}% ⚠️(偏低)")
        else:
            reasons.append(f"换手率 {s['turnover']:.1f}% ⚠️(偏高)")
        
        # 4. 概念归类
        concepts = guess_concept(s['name'], s['code'])
        s['concepts'] = concepts
        
        results.append({
            **s,
            'bj_score': score,
            'bj_reasons': reasons,
            'bj_flags': ' '.join(flags),
            'bj_rank': score,  # will sort by this
        })
    
    # 按得分排序
    results.sort(key=lambda x: (-x['bj_score'], -x['pct']))
    return results


def apply_chen_strategy(stocks, all_scored):
    """陈小群：龙头战法分析"""
    # 统计板块效应
    sector_count = {}
    for s in all_scored:
        for c in s.get('concepts', []):
            sector_count[c] = sector_count.get(c, 0) + 1
    
    # 找出强势板块 (>=3只涨停)
    strong_sectors = {k: v for k, v in sector_count.items() if v >= 3 and k != '其他'}
    
    # 在每个强势板块中找龙头
    dragons = []
    for sector, count in sorted(strong_sectors.items(), key=lambda x: -x[1]):
        sector_stocks = [s for s in all_scored if sector in s.get('concepts', [])]
        # 按换手率排序（交易最活跃的可能是龙头）
        sector_stocks.sort(key=lambda x: -x['turnover'])
        
        top3 = sector_stocks[:3]
        for rank, s in enumerate(top3):
            dragons.append({
                **s,
                'sector': sector,
                'sector_count': count,
                'sector_rank': rank + 1,
            })
    
    return dragons, strong_sectors


# ── 输出格式化 ─────────────────────────────────────
def format_report(all_scored, dragons, strong_sectors, total_stocks):
    """生成完整的 Markdown 筛选报告"""
    today = datetime.now().strftime("%Y-%m-%d %A")
    
    lines = []
    lines.append(f"# 📊 A股涨停股策略筛选报告")
    lines.append(f"**日期**: {today} (盘后自动生成)")
    lines.append(f"**全市场主板涨停数**: {total_stocks} 只")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # ── 北京炒家 首板筛选 ──
    lines.append("## 🔥 一、「北京炒家」首板战法筛选")
    lines.append("")
    lines.append(f"> 条件：主板涨停 | 流通市值 {BJ_MIN_NMC}-{BJ_MAX_NMC}亿 | 股价 < {BJ_MAX_PRICE}元 | 换手率 2%-25% | 有板块效应优先")
    lines.append("")
    
    # Top matches (score >= 3)
    top_matches = [s for s in all_scored if s['bj_score'] >= 3]
    mid_matches = [s for s in all_scored if s['bj_score'] == 2]
    low_matches = [s for s in all_scored if s['bj_score'] < 2]
    
    if top_matches:
        lines.append("### 🏆 高分匹配（得分 ≥ 3）")
        lines.append("")
        lines.append("| 排名 | 代码 | 名称 | 价格 | 涨幅 | 流通市值 | 换手率 | PE | 概念 |")
        lines.append("|------|------|------|------|------|----------|--------|-----|------|")
        for i, s in enumerate(top_matches[:15], 1):
            lines.append(
                f"| {i} | {s['code']} | {s['name']} | ¥{s['price']:.2f} | "
                f"+{s['pct']:.2f}% | {s['nmc_yi']:.1f}亿 | {s['turnover']:.1f}% | "
                f"{s['pe']} | {', '.join(s['concepts'][:2])} |"
            )
        lines.append("")
    
    if mid_matches:
        lines.append("### 📊 中等匹配（得分 = 2）")
        lines.append("")
        lines.append("| 代码 | 名称 | 价格 | 涨幅 | 流通市值 | 换手率 | 概念 |")
        lines.append("|------|------|------|------|----------|--------|------|")
        for s in mid_matches[:10]:
            lines.append(
                f"| {s['code']} | {s['name']} | ¥{s['price']:.2f} | "
                f"+{s['pct']:.2f}% | {s['nmc_yi']:.1f}亿 | {s['turnover']:.1f}% | "
                f"{', '.join(s['concepts'][:2])} |"
            )
        lines.append("")
    
    # ── 板块效应分析 ──
    lines.append("---")
    lines.append("")
    lines.append("## 📈 二、板块效应分析")
    lines.append("")
    
    if strong_sectors:
        lines.append("| 板块 | 涨停数 | 强度 |")
        lines.append("|------|--------|------|")
        for sector, count in sorted(strong_sectors.items(), key=lambda x: -x[1]):
            bar = "🔥" * min(count, 5)
            lines.append(f"| {sector} | {count} 只 | {bar} |")
        lines.append("")
    
    # ── 陈小群 龙头分析 ──
    lines.append("---")
    lines.append("")
    lines.append("## 🐉 三、「陈小群」龙头战法分析")
    lines.append("")
    lines.append("> 心法：只做主线人气总龙头，宁做主线龙尾，不做杂毛票")
    lines.append("")
    
    if dragons:
        for sector in strong_sectors:
            sector_dragons = [d for d in dragons if d['sector'] == sector]
            if not sector_dragons:
                continue
            lines.append(f"### {sector}板块（{strong_sectors[sector]}只涨停）")
            lines.append("")
            lines.append("| 排名 | 代码 | 名称 | 价格 | 涨幅 | 换手率 | 流通市值 | 龙头概率 |")
            lines.append("|------|------|------|------|------|--------|----------|----------|")
            for d in sector_dragons[:3]:
                # 龙头概率打分
                dragon_score = 0
                signals = []
                if d['turnover'] >= 10:
                    dragon_score += 1
                    signals.append("高换手")
                if d['nmc_yi'] <= 60:
                    dragon_score += 1
                    signals.append("小市值")
                if d['price'] < 20:
                    dragon_score += 1
                    signals.append("低价")
                prob = "⭐" * max(1, dragon_score)
                
                lines.append(
                    f"| {d['sector_rank']} | {d['code']} | {d['name']} | "
                    f"¥{d['price']:.2f} | +{d['pct']:.2f}% | {d['turnover']:.1f}% | "
                    f"{d['nmc_yi']:.1f}亿 | {prob} {'+'.join(signals)} |"
                )
            lines.append("")
    else:
        lines.append("*今日无明显的板块集群效应*")
        lines.append("")
    
    # ── 风险提示 ──
    lines.append("---")
    lines.append("")
    lines.append("## ⚠️ 风险提示")
    lines.append("")
    lines.append("- 本报告由脚本自动生成，仅供学习参考，**不构成任何投资建议**")
    lines.append("- 涨停次日可能高开低走，打板本质是博弈次日溢价，风险极高")
    lines.append("- 筛选条件基于公开策略框架，实际交易需结合盘口、封单量、消息面综合判断")
    lines.append("- 请勿据此操作，盈亏自负")
    
    return '\n'.join(lines)


# ── 主流程 ────────────────────────────────────────
def main():
    now = datetime.now()
    
    # 周末静默（不输出 = 不发送通知）
    if now.weekday() >= 5:
        return ''
    
    # 盘前静默（16:00之前不运行）
    if now.time() < time(15, 30):
        return ''
    
    # 获取数据
    stocks = get_all_limit_up_stocks()
    
    if not stocks:
        return ''  # 无数据时静默
    
    total = len(stocks)
    
    # 北京炒家筛选
    scored = apply_beijing_strategy(stocks)
    
    # 陈小群龙头分析
    dragons, strong_sectors = apply_chen_strategy(stocks, scored)
    
    # 生成报告
    report = format_report(scored, dragons, strong_sectors, total)
    
    return report


if __name__ == '__main__':
    output = main()
    if output:
        print(output)
