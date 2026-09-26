import json
import re
import math
import collections
import os
import sys

# ==============================================================================
# 難易度細分化テーブル生成スクリプト (generate_subdivided_tables.py)
# 手段1: ハイブリッド難易度帯切替方式 (sl/st/sr/insane/normal の最適選択)
# 手段2: 通常難易度表換算 (☆1〜☆12) の導入 (sl0等の下位帯の精密分散)
# 手段3: BMS-IR統計指標 (平均EXスコア率・プレイ人数) による同値タイブレーク
# 手段5: BMS-IR確度 (Confidence: 実測/高/中/低) による外れ値平滑化
# ==============================================================================

def parse_est(comment, prefix):
    """comment文字列から指定プレフィックスの推定難度(小数)を抽出する"""
    if not comment:
        return None
    m = re.search(rf'{re.escape(prefix)}\s*([0-9]+\.[0-9]+)', comment, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None

def parse_confidence(comment):
    """comment文字列から信頼度 (実測 / 高 / 中 / 低) を抽出する"""
    if not comment:
        return 'unknown'
    m = re.search(r'信頼度\s*([^/]+)', comment)
    if m:
        c = m.group(1).strip()
        if '実測' in c: return 'measured'
        if '高' in c: return 'high'
        if '中' in c: return 'medium'
        if '低' in c: return 'low'
    return 'unknown'

def parse_stats(item):
    """comment文字列からプレイ人数 (players) と平均EXスコア率 (avg EX) を抽出する"""
    if not item:
        return None, None
    c = item.get('comment', '')
    players = None
    avg_ex = None
    m_p = re.search(r'players\s+([0-9,]+)', c)
    if m_p:
        try:
            players = int(m_p.group(1).replace(',', ''))
        except ValueError:
            players = None
    m_ex = re.search(r'avg\s+EX\s+([0-9]+\.?[0-9]*)%', c)
    if m_ex:
        try:
            avg_ex = float(m_ex.group(1))
        except ValueError:
            avg_ex = None
    return players, avg_ex

def load_json_map(path):
    m = {}
    if not os.path.exists(path):
        print(f"Warning: {path} not found")
        return m
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        data = json.load(f)
    for x in data:
        if isinstance(x, dict) and 'md5' in x:
            m[x['md5'].lower()] = x
    print(f"Loaded {len(m)} items from {os.path.basename(path)}")
    return m

def get_chart_primary_estimate(chart, table_type, level_num, sl_rec, st_rec, sr_rec, insane_rec, normal_rec):
    """
    手段1 & 手段2: 難易度帯に応じた最適なリコメンドソースを選択して推定値と信頼度を返す
    """
    md5 = str(chart.get('md5', '')).lower()
    item_native = sl_rec.get(md5) if table_type == 'sl' else (st_rec.get(md5) if table_type == 'st' else sr_rec.get(md5))
    item_insane = insane_rec.get(md5)
    item_normal = normal_rec.get(md5)

    est_native = parse_est(item_native.get('comment', ''), table_type) if item_native else None
    est_insane = parse_est(item_insane.get('comment', ''), '★') if item_insane else None
    est_normal = parse_est(item_normal.get('comment', ''), '☆') if item_normal else None

    primary_est = None
    primary_conf = 'unknown'
    source_name = 'none'

    if table_type == 'sl':
        if level_num == 0:
            # sl0: 手段2 (☆通常換算を最優先。★1.00下限クリップを回避)
            if est_normal is not None:
                primary_est, primary_conf, source_name = est_normal, parse_confidence(item_normal.get('comment', '')), 'normal_☆'
            elif est_native is not None:
                primary_est, primary_conf, source_name = est_native, parse_confidence(item_native.get('comment', '')), 'native_sl'
        elif level_num == 12:
            # sl12: 手段1 (★発狂換算を最優先。上限張り付き89曲の頭打ちを完全解消)
            if est_insane is not None:
                primary_est, primary_conf, source_name = est_insane, parse_confidence(item_insane.get('comment', '')), 'insane_★'
            elif est_native is not None:
                primary_est, primary_conf, source_name = est_native, parse_confidence(item_native.get('comment', '')), 'native_sl'
        else:
            # sl1〜sl11: Native優先、フォールバックで★、さらに☆
            if est_native is not None:
                primary_est, primary_conf, source_name = est_native, parse_confidence(item_native.get('comment', '')), 'native_sl'
            elif est_insane is not None:
                primary_est, primary_conf, source_name = est_insane, parse_confidence(item_insane.get('comment', '')), 'insane_★'
            elif est_normal is not None:
                primary_est, primary_conf, source_name = est_normal, parse_confidence(item_normal.get('comment', '')), 'normal_☆'

    elif table_type == 'st':
        if level_num == 0:
            # st0: 手段1 (★発狂換算を最優先。下限154曲の床打ちを完全解消)
            if est_insane is not None:
                primary_est, primary_conf, source_name = est_insane, parse_confidence(item_insane.get('comment', '')), 'insane_★'
            elif est_native is not None:
                primary_est, primary_conf, source_name = est_native, parse_confidence(item_native.get('comment', '')), 'native_st'
        elif 7 <= level_num <= 12:
            # st7〜st12: 手段1 (★発狂換算を最優先。欠損を解消し高精度個別値を付与)
            if est_insane is not None:
                primary_est, primary_conf, source_name = est_insane, parse_confidence(item_insane.get('comment', '')), 'insane_★'
            elif est_native is not None:
                primary_est, primary_conf, source_name = est_native, parse_confidence(item_native.get('comment', '')), 'native_st'
        else:
            # st1〜st6: Native優先、フォールバックで★
            if est_native is not None:
                primary_est, primary_conf, source_name = est_native, parse_confidence(item_native.get('comment', '')), 'native_st'
            elif est_insane is not None:
                primary_est, primary_conf, source_name = est_insane, parse_confidence(item_insane.get('comment', '')), 'insane_★'

    elif table_type == 'sr':
        # sr: ☆通常換算がある場合は優先 (srは固定値が多いため☆で精密分散)、次いでNative、★
        if est_normal is not None:
            primary_est, primary_conf, source_name = est_normal, parse_confidence(item_normal.get('comment', '')), 'normal_☆'
        elif est_native is not None:
            primary_est, primary_conf, source_name = est_native, parse_confidence(item_native.get('comment', '')), 'native_sr'
        elif est_insane is not None:
            primary_est, primary_conf, source_name = est_insane, parse_confidence(item_insane.get('comment', '')), 'insane_★'

    return primary_est, primary_conf, source_name

def subdivide_table_advanced(local_table_path, table_type, output_path,
                             sl_rec, st_rec, sr_rec, insane_rec, normal_rec, stats_rec):
    print(f"\n==========================================")
    print(f" Processing {table_type.upper()} table (Advanced Pipeline)")
    print(f" Local: {local_table_path}")
    print(f" Output: {output_path}")
    print(f"==========================================")

    with open(local_table_path, 'r', encoding='utf-8') as f:
        local_charts = json.load(f)
    print(f"Loaded {len(local_charts)} charts from local table")

    # 難易度帯ごとに分類
    by_level = collections.defaultdict(list)
    for chart in local_charts:
        lvl_str = str(chart.get('level', '')).strip()
        num_str = re.sub(rf'^{table_type}', '', lvl_str, flags=re.IGNORECASE)
        by_level[num_str].append(chart)

    subdivided_charts = []
    
    def level_sort_key(k):
        try:
            return (0, int(k))
        except ValueError:
            return (1, k)

    total_identical_val_checks_passed = True

    for level_key in sorted(by_level.keys(), key=level_sort_key):
        charts = by_level[level_key]
        n_total = len(charts)
        try:
            level_num = int(level_key)
        except ValueError:
            level_num = 0

        print(f"\n--- Level {table_type}{level_key} ({n_total} charts) ---")

        # 各曲の推定難度およびメタデータ・IR統計データを抽出
        chart_items = []
        for c in charts:
            md5 = str(c.get('md5', '')).lower()
            est, conf, source_name = get_chart_primary_estimate(
                c, table_type, level_num, sl_rec, st_rec, sr_rec, insane_rec, normal_rec
            )
            item_stats = stats_rec.get(md5)
            players, avg_ex = parse_stats(item_stats)

            notes = 0
            try:
                notes = int(c.get('notes', 0) or c.get('totalnotes', 0) or 0)
            except (ValueError, TypeError):
                notes = 0

            chart_items.append({
                'chart': c,
                'md5': md5,
                'est': est,
                'conf': conf,
                'source': source_name,
                'players': players,
                'avg_ex': avg_ex,
                'notes': notes,
                'title': str(c.get('title', ''))
            })

        # 欠損曲へのフォールバック（既知の中央値）
        known_ests = [x['est'] for x in chart_items if x['est'] is not None]
        try:
            default_est = float(level_key) + 0.5
        except ValueError:
            default_est = 0.5
        median_est = sorted(known_ests)[len(known_ests) // 2] if known_ests else default_est

        known_ex = [x['avg_ex'] for x in chart_items if x['avg_ex'] is not None]
        median_ex = sorted(known_ex)[len(known_ex) // 2] if known_ex else 75.0

        missing_count = 0
        for it in chart_items:
            if it['est'] is None:
                missing_count += 1
                it['est'] = median_est

            # 手段5: 確度「低」の外れ値平滑化 (中央値寄りに50%引き戻す)
            eff_est = it['est']
            if it['conf'] == 'low':
                eff_est = 0.5 * eff_est + 0.5 * median_est
            it['effective_est'] = eff_est

            # 手段3: BMS-IR統計指標の補正
            eff_ex = it['avg_ex'] if it['avg_ex'] is not None else median_ex
            it['effective_ex'] = eff_ex

            # 複合ソートタプル:
            # 1. effective_est (昇順: 易しい -> 難しい)
            # 2. -eff_ex (降順: EXスコア率が高い=易しい -> 低い=難しい)
            # 3. -players (降順: プレイ人数が多い=一般化されている)
            # 4. notes (昇順: ノーツ数が少ない=易しい -> 多い=難しい)
            # 5. title (昇順: タイトル順)
            it['sort_tuple'] = (
                eff_est,
                -eff_ex,
                -(it['players'] if it['players'] is not None else 0),
                it['notes'],
                it['title']
            )

        if missing_count > 0:
            print(f"  Note: {missing_count} charts had missing estimates, assigned fallback median={median_est:.2f}")

        # ソート実行
        chart_items.sort(key=lambda x: x['sort_tuple'])

        # 同一グループ判定 (est, avg_ex, players, notes が完全同値のグループ)
        group_key_map = collections.defaultdict(list)
        for idx, it in enumerate(chart_items):
            strict_key = (
                round(it['effective_est'], 4),
                round(it['effective_ex'], 2),
                it['players'],
                it['notes']
            )
            group_key_map[strict_key].append((idx, it))

        assigned_subtiers = {}
        for strict_key, grp in group_key_map.items():
            indices = [idx for idx, it in grp]
            mid_idx = sum(indices) / len(indices)
            sub_tier = min(9, int(math.floor((mid_idx * 10) / n_total)))
            assigned_subtiers[strict_key] = sub_tier

        distribution = collections.defaultdict(int)
        for strict_key, grp in group_key_map.items():
            sub_tier = assigned_subtiers[strict_key]
            sub_level_str = f"{level_key}.{sub_tier}"
            for idx, it in grp:
                c = dict(it['chart'])
                c['level'] = sub_level_str
                c['estimated_difficulty'] = round(it['effective_est'], 2)
                c['subdivision_source'] = it['source']
                if it['players'] is not None:
                    c['ir_players'] = it['players']
                if it['avg_ex'] is not None:
                    c['ir_avg_ex'] = it['avg_ex']
                subdivided_charts.append(c)
                distribution[sub_tier] += 1

        # 同一キーグループが同一サブレベルに割り振られたか検証
        for strict_key, grp in group_key_map.items():
            expected_tier = assigned_subtiers[strict_key]
            for idx, it in grp:
                target_c = [c for c in subdivided_charts if c.get('md5') == it['chart'].get('md5')][-1]
                actual_tier = int(target_c['level'].split('.')[1])
                if actual_tier != expected_tier:
                    total_identical_val_checks_passed = False
                    print(f"  ERROR: Identical value mismatch for key={strict_key}")

        dist_strs = [f".{tier}:{distribution[tier]}" for tier in range(10)]
        print("  Distribution (.0 to .9): " + ", ".join(dist_strs))

    print(f"\nAll identical value groupings verified: {total_identical_val_checks_passed}")

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(subdivided_charts, f, ensure_ascii=False, indent=2)
    print(f"Successfully saved {len(subdivided_charts)} charts to {output_path}")

# ==============================================================================
# 旧コード (コメントアウト保持)
# 理由: 手段1, 2, 3, 5の統合前の、単一リコメンドソース依存・同値集中が発生していた旧配分関数
# ==============================================================================
# def subdivide_table(local_table_path, recommend_data_path, table_type, output_path):
#     with open(local_table_path, 'r', encoding='utf-8') as f:
#         local_charts = json.load(f)
#     rec_map = {}
#     with open(recommend_data_path, 'r', encoding='utf-8') as f:
#         rec_list = json.load(f)
#     for item in rec_list:
#         if isinstance(item, dict) and 'md5' in item:
#             rec_map[item['md5'].lower()] = item
#     by_level = collections.defaultdict(list)
#     for chart in local_charts:
#         lvl_str = str(chart.get('level', '')).strip()
#         num_str = re.sub(rf'^{table_type}', '', lvl_str, flags=re.IGNORECASE)
#         by_level[num_str].append(chart)
#     ...

if __name__ == '__main__':
    rec_dir = r'F:\難易度細分化用リコメンド難易度表'
    out_dir = r'c:\Users\川野創太\Downloads\stellarate'

    print("Loading recommend and IR dataset...")
    sl_rec = load_json_map(os.path.join(rec_dir, 'sl_recommend.txt'))
    st_rec = load_json_map(os.path.join(rec_dir, 'st_recommend.txt'))
    sr_rec = load_json_map(os.path.join(rec_dir, 'sr_recommend.txt'))
    insane_rec = load_json_map(os.path.join(rec_dir, '発狂換算全譜面リコメンド.txt'))
    normal_rec = load_json_map(os.path.join(rec_dir, 'genocide_normal_recommend.json'))
    stats_rec = load_json_map(os.path.join(rec_dir, 'bmsir_stats_7k.json'))

    tables = [
        ('sl', 'sl_score.json', 'sl_subdivided.json'),
        ('st', 'st_score.json', 'st_subdivided.json'),
        ('sr', 'sr_score.json', 'sr_subdivided.json')
    ]

    for table_type, local_file, out_file in tables:
        local_path = os.path.join(out_dir, local_file)
        out_path = os.path.join(out_dir, out_file)
        subdivide_table_advanced(
            local_path, table_type, out_path,
            sl_rec, st_rec, sr_rec, insane_rec, normal_rec, stats_rec
        )
