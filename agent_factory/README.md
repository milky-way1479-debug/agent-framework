# Human × Agent governance extension v0.1

Microsoft Agent Frameworkに、版固定したAI憲法・AI法律と、所有者が統制する実行機能を接続します。
この追加部分はユーザーのフォーク専用であり、Microsoftが保守する公式機能ではありません。

## できること

1. Layer 1・2の原文と設定のハッシュを、起動時・提案時・実行前に確認する。
2. MicrosoftのAgentが提案を作り、所有者の決定を待つ。モデルに承認・実行機能は渡さない。
3. 所有者が操作の内容・版・期限を確認して承認または拒否する。
4. 未使用で一致する承認がある場合だけ、登録済み模擬Toolを一度実行する。
5. 結果を別の検証関数で確認し、COMPLETED / UNVERIFIED / RESULT_UNKNOWNを報告する。
6. 親タスクの停止を子タスクへ伝え、未実行の承認を取り消す。

追加部分を使う入口だけが統制対象です。元のSDKを直接呼び出すサンプルが、この追加機能で自動的に保護されるわけではありません。
全ての利用経路を統制した本番システムを完成させたという意味ではありません。

## 構成

| ファイル | 役割 |
|---|---|
| `human_agent_governance/policy.py` | 原文・設定・許可Tool・引数を検査する |
| `runtime.py` | 提案、本人の決定、実行、停止、結果確認を管理する |
| `ledger.py` | SQLiteの同時実行制御と鍵付き監査記録を管理する |
| `framework.py` | Microsoftの公開Agent・Middleware APIへ接続する |
| `skills.py` | 隔離済み外部Skillの一覧・版を取得する。実行や承認はしない |
| `demo.py` | ネット接続のない動作確認を提供する |
| `tests/` | 承認回避、重複、停止、改変、障害、SDK接続を試験する |

## インストールと動作確認

Python 3.10以上。リポジトリのルートで、専用の仮想環境を作成します。

```sh
python -m venv .venv
# Windowsの場合、以下の .venv/bin/python を .venv/Scripts/python に置き換えます。
.venv/bin/python -m pip install -e ./python/packages/core -e './agent_factory[test]' ruff==0.16.10
.venv/bin/python -m human_agent_governance.demo --repository .
.venv/bin/python -m pytest agent_factory/tests -q
.venv/bin/python -m ruff check agent_factory
```

demoは提案を表示し、所有者が `YES` と入力した場合にだけ、文字列を大文字へ変える模擬Toolを実行します。
拒否して終了する場合は別の文字列を入力します。LLM APIキー、Google、GitHub、メールには接続しません。
CIでは `--simulate-owner-approval` を明示指定して、模擬所有者の承認を試験します。このオプションは模擬demoだけに存在します。

SDK接続は、このフォークに含まれる `agent-framework-core==1.19.0` で試験しています。
.NETのコアやサンプルは変更しておらず、.NET用統制アダプターは本版の対象外です。

## 所有者とモデルの境界

モデルに渡すのは `propose_action` のみです。このToolは提案を記録するだけで副作用操作を行いません。
所有者の権限オブジェクト、台帳の鍵、登録済み実行関数は、信頼できるホスト側だけが保持します。
エージェントに任意Python・シェル・OS操作を渡すことは、本構成の境界を壊します。

実サービスに接続する前の追加条件は [BOUNDARIES.md](docs/BOUNDARIES.md)、
本番有効化の未完了条件は [ACTIVATION_CHECKLIST.md](docs/ACTIVATION_CHECKLIST.md) に記載しています。
復旧方法は [ROLLBACK.md](docs/ROLLBACK.md) を参照してください。
