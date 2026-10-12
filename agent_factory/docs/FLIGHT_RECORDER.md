# Agent Flight Recorder — MVP設計・運用・限界

状態：オフライン模擬研究用。既存開発ブランチに対する追加コンポーネント。
本番デプロイ、実サービス接続、規範の制定・改正、PRマージは行わない。

## 調査結果と実装方針

基準コミット：`b56e8c372d1034c9f83c8c6591fda6ecc2cac08f`。
`agent_factory` は提案・単回承認・実行・検証・停止を実装済み。
`runtime.py` の承認照合・共有上限・親子停止と `ledger.py` のSQLiteトランザクションを再利用する。
これらの既存ファイル、MicrosoftのPython/.NET本体、規範の原文・manifest・研究設定は変更しない。

Microsoftの `python/packages/core/agent_framework/observability.py` には公開 `get_tracer()` と
Agent/ToolのTracing、任意のExporter設定、機密Telemetryの設定がある。
追加ゲートウェイは `agent_framework.observability.get_tracer()` で実行Spanを生成し、
有効なTrace ID/Span IDを監査イベントに関連付ける。Exporterは自動起動せず、外部へ送信しない。
Sampling、未設定のTracer、Exporterの成否を監査の成否とみなさない。監査は別プロセスで同期確認する。

Layer 1とLayer 2は取得元原本と版固定したコピーを確認した。いずれも正式制定前の草案であり、
今回の開発依頼は正式制定・運用有効化ではない。以下はその原則に従う研究実装であって、全条項の完了宣言ではない。

| 上位要件 | 実装 | 残る条件 |
|---|---|---|
| CONST-002/004/005、LAW-011 | 5W1H・実引数・費用・検証条件・限界を人間へ提示。命令の鍵付き照合 | 本人認証、実際の利用者による監督理解の検証 |
| CONST-006、LAW-004/008/023 | 既存許可Tool/引数/上限、単回承認、外部送信は全拒否 | 全既存アプリ・SDK経路の実運用棚卸しと封鎖 |
| CONST-007、LAW-021 | 人間用停止、進行中の協調停止、監査障害時のローカル停止 | 強制停止・リモート停止確認・安全な終了枠 |
| CONST-008、LAW-018/022 | 生データ非保存、最小イベントSchema、鍵付き照合値 | 保持期限、閲覧権限、第三者見直し、外部送信審査 |
| LAW-003/014/015 | 独立開始記録、登録済み検証関数、結果不明・照合、再実行禁止 | 実サービスでの効果確認・冪等性・独立証拠取得 |

上位規範を変更する必要はない。本番条件の不足を下位設定やこの文書で緩和しない。

## 境界とデータの流れ

1. モデルはタスクに結び付けた `propose_action` だけを持つ。所有者権限・監査Client・秘密値・実行関数は渡さない。
2. `ExecutionGateway` が要求を記録し、既存PolicyでTool・引数・タスクを検査する。
3. モデルの5W1H（who/what/when/where/why/how）をシステムの主体・Tool・期限・ローカル対象・目的・命令Digestと照合。
   不一致は拒否する。5W1Hは権限を発行する情報ではない。実引数は人間用previewで別途見せる。
4. 人間専用コンソールがpreviewを表示し、YES/NOの明示入力で承認・拒否する。
   各Taskの未処理要求は一件。拒否はTaskを停止し、同じTaskから別IDで再申請できない。
5. 実行時は既存SQLiteで承認期限・版・引数・予算を一体検証し、一度だけ承認を消費。
   登録Handlerの直前に独立監査の権限許可・開始記録を確認する。確認不能ならHandlerを呼ばない。
6. 結果は登録済みHandlerと別のVerifierから取得。Verifierがliteral Trueの場合だけ成功。
   例外・タイムアウト・取消しは結果不明、検証不成立はUNVERIFIED。関係Taskを停止する。
7. 検証済み出力の完全一致を確認してから、hostがhandoffを記録してコピーを渡す。
   コピーに承認・実行権限・Task権限は含めない。宛先は新しい提案と人間承認を必要とする。

任意のツール通信を傍受する機能ではない。`handoff`経路に明示的に接続した引き渡しだけが追跡対象。
今回登録できる実行Toolは既存設定の `uppercase_mock` のみ。外部送信許可リストは空である。
実サービスの宛先・リダイレクト・DNS/プロキシ・ToolごとのEgress検証は未実装。

## 独立した保存機構

`service.py` は別プロセスで `AuditStore` を所有する。実行台帳とは別のJSONLへ追記し、
連続番号・直前署名・HMAC-SHA256を保存する。秘密の署名鍵はRecorder専用ファイルにあり、Client APIでは返さない。
append/read以外の操作を受け付けず、readでもChainとCheckpointを検証する。
起動には既存Storeを使い、明示的な `--provision` の初回だけ空のStoreを作る。
不足ファイルを自動再生成しない。同一Storeの同時WriterはOSのファイルロックで拒否する。

各appendはログをfsyncしてから別ディレクトリのCheckpointを更新・fsyncし、確認応答する。
欠落・改変・並べ替え・末尾切捨て・ログ単体の巻戻し・ファイル消失・違う署名鍵を検出する。
ログとCheckpointの間でクラッシュすれば不一致のまま停止し、勝手な修復や成功判定をしない。
通信確認には要求ごとのIDを照合する。パイプが故障・タイムアウト・拒否されたら再利用しない。

**防げないこと：** 管理者またはRecorder自身が鍵・ログ・Checkpointを全部支配する場合、
正しい署名で偽ログを作ること、三者を整合した旧版へ戻すこと、全削除・DoSを完全には防げない。
Gatewayの侵害による虚偽のappendも防げない。Recorderは記録主体であって実効果の第三者認証機関ではない。
独立ホストの単調Anchor、WORM/Object Lock、外部署名・独立Witness、監査鍵ローテーションは未実装。
ローカルCheckpointをそれらの代替と扱わない。

## 記録する情報と記録しない情報

| 記録できる | 記録しない／保証しない |
|---|---|
| 要求・提案・権限判定・拒否・承認/拒否・開始・検証結果・停止・取消し | AIの内部思考、プロンプト全文、入力/出力本文、秘密値、例外の生文字列 |
| 実行/Task/Agent/Tool/承認/人間役割のID、規範・設定Digest、日時、連番 | 本人認証済みの実名やリモートID（端末所有者は研究用の仮定） |
| 5W1H・操作内容の鍵付きDigest、検証済み出力のDigest、明示handoff | 独立証拠の原本、preview本文の長期復元、任意の通信や引き渡し |
| 有効なOTel Trace ID/Span ID | SamplingされたSpanの全保存、Exporter障害のない配信 |
| 未完了開始と結果不明、人間の照合記録 | 停電中など記録手段が全て失われた時間帯の詳細、実世界の効果/取消し |

具体的な操作のpreviewは今回のhostセッション中に限り閲覧できる。長期監査から本文を復元できない。
本番で詳細証拠が必要なら、目的・閲覧者・機密分類・保持期限を人間が定めた別の証拠保管庫が必要。
データが監査に入らないことと、承認画面・SDKの通常Tracingにも出ないことは別。
Sensitive TelemetryやTool引数のTracingは無効のままにし、外部Exporterを勝手に設定しない。

## OSと権限の分離

パイプモード：hostだけが専用の子RecorderへのパイプとTokenを持つ。モデルには渡さない。
開発demoは同一UIDであり、host上の任意コードに対するユーザー単位の分離ではない。
モデルにShell/Python/File/MCP Toolを追加することは禁止条件であり、この禁止をPromptだけで実現したと扱わない。

追加した `sandbox.confine_memory_only()` は、Linux x86_64の子Plannerに対しseccompを設定する。
新規ファイルの読取/書込/削除、ネットワーク、他プロセスアクセス、シグナル、プロセス生成を拒否し、
Recorder等の継承FDを閉じる。依存を事前ロードした、メモリ内処理とstdin/stdoutだけの模擬Plannerに限定。
秘密を除去した環境・close_fds付きの新規子プロセスで設定後にPlannerを動かす必要がある。
この設定前のコード、ホスト自体、カーネル、CPU/メモリDoS、全Syscallに対するセキュリティ証明は対象外。
GatewayとRecorderには適用しない。実行中host内で任意のLLM生成コードを実行して安全とは主張しない。

`sandbox.confine()` はLandlockで読取パス・専用workspaceを制限する別モード。
利用不能なら拒否してPlannerを起動しない。検証環境ではLandlockが利用不能で、このパスの正常な実動作は未検証。
Networkが環境側でも遮断されているため、ネットワーク拒否の試験は独自seccompだけの効果を分離して測定していない。
ファイルの直接読取・改変・削除の拒否は、seccomp適用した子プロセスで実測した。

`deploy/flight-recorder/*.service.example` は、独立した `afr-planner`、`afr-gateway`、`afr-recorder` の
systemd設定案。Plannerには資格情報もSocketも保存先も与えず、GatewayはRecorderの鍵/ログ/Anchorを読めない。
Recorderは保存先だけを書ける。別UID・Filesystem・Namespace・AddressFamilies・NoNewPrivileges・上限を指定する。
**これは未配置・未起動・未検証の構成例。** UID、本人用入口、プロビジョニング、Socketディレクトリ所有権、
監査Tokenの安全な配置を人間がレビューする必要がある。架空の入口を本番完成品と扱わない。
UNIXソケット経路はUIDとTokenを照合するが、今回の環境ではSocket作成禁止のためend-to-end未検証。

## 操作手順

依存関係と試験は既存READMEの方法を使う。リポジトリのルートから：

```sh
.venv/bin/python -m pytest agent_factory/tests -q
.venv/bin/python -m ruff check agent_factory
.venv/bin/python -m human_agent_governance.flight_recorder.demo --repository .
```

Windowsは既存GovernanceRuntimeの範囲。新RecorderはLinux専用で、Windows対応は未実装。
Demoは一時ディレクトリ・ダミー文字列のみを扱い、終了時に模擬記録を破棄する。本番の保持設定ではない。

人間用端末には時系列で成功/失敗/拒否/承認待ち/実行中/結果不明/停止を表示する。
`detail <操作ID>` で記録と承認履歴、`review <操作ID>` で5W1Hと正確な実引数を確認。
`approve <操作ID>` → `YES`、`reject <操作ID>` → `NO` で決定し、`execute <操作ID>` で模擬実行する。
`stop <TaskID>` は実行中でも受け付ける。`quit` は進行中模擬操作を停止・取消して終了する。
停止は新規開始を止めるもので、協調しないCallbackを強制殺害したり既存効果を取り消すものではない。
Web画面・スマホUI・リモート認証・通知は今回未実装。端末を操作する人を研究用所有者とする。

## 障害・復旧・照合

- 開始前の独立記録失敗：Handlerを呼ばず、Gatewayをラッチ停止。自動再送・再開はしない。
- 操作後の記録失敗：成功を返さない。独立開始記録が未完了として残る。実効果がないとは推定しない。
- hostが落ちた場合：旧Executorが確実に停止したことを所有者が先に確認する。
  新しいhostで `recover_interrupted(owner_authority)` を呼び、独立開始に完了記録のない操作を結果不明へ移す。
  既存台帳側だけにCOMPLETEDがあっても独立結果がない場合は関係操作を保留する。
- `reconcile(operation_id, observed_status, owner_authority)` は、人間が確認した証拠の照合結果を追加記録する。
  システムの自動検証結果と区別し、承認・予算・実行状態を復活させない。証拠原本の取得は本版の範囲外。
- 再起動時、以前の承認を読み込んで実行する機能はない。停止状態は既存台帳に保存。
  コード復旧と状態復旧を分け、Ledger/ログ/Anchorを古いバックアップへ揃えて戻さない。
- Checkpoint不一致：新規操作を開始せず、コピーを安全に保全して原因・残存ログ・外部証拠を人間が確認する。
  Checkpointだけ更新して整合したことにする自動修復コマンドは用意しない。
- ローカル停止は監査障害中でも保持する。ただし永続台帳も壊れている場合、再起動後の独立停止保存は保証できない。
  supervisorで旧hostを隔離し、復旧を再開許可としない。

## MVPの限界と本番前の人間判断

全Chainの検証は毎操作O(n)、読取応答は8MiB上限。本番規模の並行処理、ローテーション、保持期限・削除、
鍵更新、遠隔閲覧、アーカイブ、ホスト横断停止、.NET用アダプター、実サービス冪等性は未実装。
二つの保存先と外部操作を原子的にコミットする保証はない。開始済み記録はCallback実行の可能性であり、必ず実行された証明ではない。

元のSDK・別のGovernanceRuntime・他アプリの直接API呼出しを、この追加だけで全て閉鎖したとは主張しない。
そのため本番モードは既存Policyにより拒否したまま。実運用前には [ACTIVATION_CHECKLIST.md](ACTIVATION_CHECKLIST.md)
に加えて、独立OSユーザー実測、監査保全先、本人認証、保持期限、回復証拠、全権限経路の排除と
利用者による監督試験が必要。Layer 1/2の変更案は今回不要であり、原本を変更していない。

本番デプロイ・実アカウント操作・規範の改正・PRマージは人間の明示承認が必要。
