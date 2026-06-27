# rclone 設定ガイド (Google Drive 連動)

KoeRadi Archive Server で録音された音声データ (`data/audio/`) およびメタデータ (`data/metadata/metadata.json`) を Google Drive へ自動同期するための rclone 設定手順書です。

---

## 1. rclone のインストール

Raspberry Pi に rclone がインストールされていない場合は、以下のコマンドでインストールします。

```bash
sudo apt update
sudo apt install -y rclone
```

インストール後、バージョンを確認します。

```bash
rclone version
```

---

## 2. Google Drive のリモート設定 (`koeradi-drive`)

Google Drive との連携設定を行います。リモート名は **`koeradi-drive`** に指定する必要があります。

```bash
rclone config
```

対話型セットアップの入力例:

1. **`n`** (New remote) を選択
2. **`name`**: `koeradi-drive` と入力
3. **`Storage`**: `drive` (Google Drive) を選択（リストから番号または `drive` を入力）
4. **`client_id` / `client_secret`**: 空白のまま Enter（デフォルトを使用）
5. **`scope`**: `1` (Full access...) を選択
6. **`root_folder_id` / `service_account_file`**: 空白のまま Enter
7. **`Edit advanced config`**: `n` (No)
8. **`Use web browser to automatically authenticate rclone?`**:
   - Raspberry Pi 上でデスクトップ/ブラウザが使える場合は `y` を選択してログイン承認します。
   - ヘッドンホスト（SSHのみ）の場合は `n` を選択し、指示に従って別PCでトークンを生成し貼り付けます。
9. **`Configure this as a Shared Drive (Team Drive)?`**: `n` (No)
10. 最後に設定内容を確認して **`y`** (Yes this is OK) を選択し、**`q`** で終了します。

---

## 3. 設定確認方法

設定されたリモート一覧を確認します。`koeradi-drive:` が表示されれば成功です。

```bash
rclone listremotes
```

**出力例:**
```text
koeradi-drive:
```

Google Drive 内のファイル一覧を試す場合:
```bash
rclone lsd koeradi-drive:
```

---

## 4. 同期スクリプトの使い方

プロジェクト配下の `scripts/sync_drive.sh` を使用して同期を行います。

### 🔍 dry-run 同期（確認モード）
実際の転送を行わず、同期対象とテストのみを行います。

```bash
bash scripts/sync_drive.sh --dry-run
```

### 🚀 本番同期
ローカルの `data/` フォルダ全体を Google Drive 上の `KoeRadiArchive` フォルダへ同期します。同期前に自動で `generate_metadata.py` が実行されます。

```bash
bash scripts/sync_drive.sh
```

**同期後の Google Drive 構造:**
```text
KoeRadiArchive/
├── audio/
│   ├── TBS/
│   │   └── 2026-06-27_TBS_test_program.m4a
│   └── sample/
│       └── 2026-06-28_TBS_sample.m4a
└── metadata/
    └── metadata.json
```
