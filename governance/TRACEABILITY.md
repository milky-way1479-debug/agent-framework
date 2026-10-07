# 憲法・法律と実装の対応

この表は34項目の追跡用資料です。「模擬範囲で実装」は、限定されたオフライン研究経路で検証したという意味です。
全文の適合保証、本番稼働の承認、安全率の採点ではありません。文章の判断が必要な事項と環境の強制は、表の未完了条件を残しています。

## Layer 1

| 項目 | このブランチでの対応 | 残る本人の判断・本番条件 |
|---|---|---|
| CONST-001 力・決定・責任 | policyの固定研究目的、hostのtask作成、モデルは提案のみ | 実業務の目的・責任範囲の指定 |
| CONST-002 役割・判断権限 | owner capability、提案Toolと実行APIの分離 | 本人認証、権限のOS／サービス分離 |
| CONST-003 社会的許容範囲 | 許可リスト、研究目的、外部操作の拒否 | 実行の社会的妥当性・第三者影響の判断 |
| CONST-004 実効的監督 | 明示承認、停止、結果検証、回避試験 | 実際の承認UIの理解可能性・運用の実効性 |
| CONST-005 根拠・限界 | 提案の操作内容・版・上限、未確認結果の区別 | 実業務の出典・根拠・留保・閲覧制限の提示 |
| CONST-006 最小権限 | 既定拒否、task scope、親子の共通上限 | 実資格情報・ファイル・通信の最小権限 |
| CONST-007 介入 | task停止、pending承認取消し、子task停止 | 外部委任停止確認、安全な終了用枠と手順 |
| CONST-008 第三者の権利 | 外部送信禁止、台帳への生データ保存を避ける | 権利判断、見直し、データ分類・保持期間 |
| CONST-009 優先順位〔条文化案〕 | L1/L2の版固定、対応表、下位設定の変更検知 | 条文の正式確定・制定 |
| CONST-010 制定改正〔条文化案〕 | 草案を維持、production拒否、自動改正なし | 本人による明示制定と改正手続き |
| CONST-011 矛盾報告〔条文化案〕 | 不適合・不足は例外としてhostへ報告し保留 | 本人による正式確定、実運用の報告経路 |

## Layer 2

実装と試験の場所は `agent_factory/human_agent_governance/` と `agent_factory/tests/` です。

| 項目 | 実装・試験した研究範囲 | 未完了の本番条件 |
|---|---|---|
| LAW-001 目的・優先順位 | policy目的、source manifest、task scope、規範変更拒否 | 目的変更・社会的影響・正式版の実運用審議 |
| LAW-002 人間の役割 | trusted hostのowner capability、偽capability拒否試験 | 所有者本人の遠隔認証、役割と責任の指定記録 |
| LAW-003 workflow | PROPOSED→APPROVED→RUNNING→Report、拒否・未確認の区別 | 実業務の完了条件・効果判定・事前許可 |
| LAW-004 最小権限 | 許可Tool・引数・task scope、root予算の共同消費、子task試験 | 実際の資源／費用台帳、終了用枠、OS強制 |
| LAW-005 Need to Know | モデルには提案Toolのみ、子scope拡大拒否、秘密を台帳へ保存しない | データ分類、正規の役割間連携、情報ACL |
| LAW-006 信頼と権限 | 高性能・成功実績による権限昇格APIなし、client交換拒否 | provider更新や実構成変更の再検証 |
| LAW-007 指示優先関係 | 原文の優先順位を指示へ含める、設定・版が不明なら拒否 | 意味的な規範矛盾の本人審議と報告手順 |
| LAW-008 外部情報 | 外部の「承認済み」では承認できない試験、未知Toolは閉じる | 全実入力・出力・委任経路の分類と情報流制約 |
| LAW-009 外部Skill審査 | inventoryのみ、UNREVIEWED固定、版変更・symlink拒否、setup.py非実行試験 | 取得元、間接依存、hooks、ライセンス、隔離実行審査 |
| LAW-010 承認対象操作 | mockもowner承認必須。外部通信・shell・remote delegate非対応 | 実操作分類、承認閾値、第三者の権利確認 |
| LAW-011 承認真正性 | 操作ID・引数・版・期限固定、single-use、同時start、取消し・replay試験 | 独立認証経路、署名された外部承認、意味的拒否回避検知 |
| LAW-012 職務分離 | modelは提案、ownerだけ決定、登録済みhandlerとverifierを分離 | 資格情報・プロセス・保存先による独立した分離 |
| LAW-013 事実等の表示 | 提案効果はmockと明記、未測定精度・実効果を表示しない | 出典・推論・仮定・反証・重要留保の実業務表示 |
| LAW-014 失敗等 | callback failure・timeout・crashはRESULT_UNKNOWN、自動再試行なし | 外部照会・重複防止条件、報告再通知・到達確認 |
| LAW-015 検証・Report | verifierがTrueの場合だけCOMPLETED、誤結果はUNVERIFIED | 実業務の効果測定・観測期間・未解決事項の追跡 |
| LAW-016 可逆性 | 別branch、code rollback手順、台帳はコードと分離 | 本番復旧・削除義務・外部影響の補償、古いbackup対策 |
| LAW-017 Sandbox First | offline mock、外部Skills非実行、production mode拒否試験 | OS隔離、昇格対象構成の固定、本番差分の検証 |
| LAW-018 記録 | SQLite原子更新、HMAC chain、状態改変・wrong-key検知、生入力非保存 | 独立した追記保全、保持削除、復元rollback検知、本人識別 |
| LAW-019 Agent設計 | purpose、Tool、scope、上限、停止、source版、完了検証を固定 | 任意Agent生成の設計schemaと審議・昇格工程 |
| LAW-020 継承・変更 | source hash、設定hash、Agent指示、正式化と有効化を自動化しない | 本人の改正決定記録、並行改正・部分切替の実装 |
| LAW-021 停止 | ancestor検査、子task／pending許可取消し、cooperative callback、再起動保持 | 待機queue、予約、remote受理、限定終了枠、実再開認証 |
| LAW-022 権利・送信 | 許可clientはofflineのみ、外部宛先引数拒否、台帳は最小記録 | 人の権利見直し、redirect含む送信検査、データ保護 |
| LAW-023 設定・実装強制 | research default-deny、回避・改変・障害テスト、失敗時host報告 | 独立強制境界、全実行先の棚卸し、実環境検証・有効化 |

## 判断上の限界

憲法の論点A〜E、CONST-009〜011の審議状態は原文のまま保持しています。
本版はPythonの統制入口を実装・検証するもので、.NET、MCP、学校Agent、承認コンソール、Googleへの接続は含めません。
実サービスを導入する際は、未完了条件を環境別に実装し、本人が対象版と構成を確認してください。
