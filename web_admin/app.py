import os
import subprocess
import yaml
from flask import Flask, render_template, request, redirect, url_for, jsonify

# Flaskアプリケーションの初期化
app = Flask(__name__)

# プロジェクトのルートディレクトリおよび設定ファイルのパスを取得
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_FILE = os.path.join(BASE_DIR, 'config', 'recording_rules.yaml')

def load_rules():
    """録音ルール設定ファイル(recording_rules.yaml)を読み込む関数"""
    if not os.path.exists(RULES_FILE):
        return []
    with open(RULES_FILE, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
        return data.get('rules', [])

def save_rules(rules):
    """録音ルール設定ファイル(recording_rules.yaml)へ書き込む関数"""
    data = {'rules': rules}
    with open(RULES_FILE, 'w', encoding='utf-8') as f:
        # 日本語が文字化けしないように allow_unicode=True、元のキー順序を保つため sort_keys=False
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)

@app.route('/')
def index():
    """トップページ: ルール一覧を表示"""
    rules = load_rules()
    return render_template('index.html', rules=rules)

@app.route('/rules/add', methods=['POST'])
def add_rule():
    """新しい録音ルールを追加するエンドポイント"""
    name = request.form.get('name', '').strip()
    keyword = request.form.get('keyword', '').strip()
    # チェックボックスの値がある場合はTrue、なければFalse (またはデフォルトTrueなど)
    enabled = request.form.get('enabled') == 'on'

    if name and keyword:
        rules = load_rules()
        rules.append({
            'name': name,
            'keyword': keyword,
            'enabled': enabled
        })
        save_rules(rules)
    
    return redirect(url_for('index'))

@app.route('/rules/toggle/<int:index>', methods=['POST'])
def toggle_rule(index):
    """ルールの有効/無効(enabled)を切り替えるエンドポイント"""
    rules = load_rules()
    if 0 <= index < len(rules):
        rules[index]['enabled'] = not rules[index].get('enabled', False)
        save_rules(rules)
    return redirect(url_for('index'))

@app.route('/rules/delete/<int:index>', methods=['POST'])
def delete_rule(index):
    """指定したルールを削除するエンドポイント"""
    rules = load_rules()
    if 0 <= index < len(rules):
        rules.pop(index)
        save_rules(rules)
    return redirect(url_for('index'))

@app.route('/run-dry-run', methods=['POST'])
def run_dry_run():
    """dry-runを実行し、実行結果を返却するエンドポイント (JavaScript/fetch用)"""
    script_path = os.path.join(BASE_DIR, 'scripts', 'run_yesterday_all.sh')
    try:
        # スクリプトを --filtered --dry-run 付きで実行
        result = subprocess.run(
            ['bash', script_path, '--filtered', '--dry-run'],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=120
        )
        output = result.stdout
        if result.stderr:
            output += "\n--- Standard Error ---\n" + result.stderr
        return jsonify({'success': True, 'output': output})
    except Exception as e:
        return jsonify({'success': False, 'output': f"実行中にエラーが発生しました: {str(e)}"})

if __name__ == '__main__':
    # LAN内からアクセス可能にするため host='0.0.0.0'、ポート 8080 で起動
    app.run(host='0.0.0.0', port=8080, debug=True)
