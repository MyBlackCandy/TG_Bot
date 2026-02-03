<?php
$db_url = getenv('DATABASE_URL');
$db_conn = parse_url($db_url);
$chat_id = $_GET['c'] ?? 0;

try {
    $pdo = new PDO("pgsql:" . sprintf(
        "host=%s;port=%s;user=%s;password=%s;dbname=%s",
        $db_conn['host'], $db_conn['port'], $db_conn['user'], $db_conn['pass'], ltrim($db_conn['path'], "/")
    ));
    $stmt = $pdo->prepare("SELECT * FROM history WHERE chat_id = ? ORDER BY timestamp DESC");
    $stmt->execute([$chat_id]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
} catch (Exception $e) { die("Database connection error."); }
?>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>账单明细</title>
    <style>
        body { font-family: -apple-system, sans-serif; background: #f0f2f5; padding: 15px; }
        .card { background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; }
        th { background: #5c67f2; color: #fff; text-align: left; padding: 10px; }
        td { padding: 10px; border-bottom: 1px solid #eee; font-size: 14px; }
        .plus { color: #28a745; font-weight: bold; }
        .minus { color: #dc3545; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <h3>📊 完整账单 (ID: <?= htmlspecialchars($chat_id) ?>)</h3>
        <table>
            <thead><tr><th>时间</th><th>姓名</th><th>金额</th></tr></thead>
            <tbody>
                <?php foreach ($rows as $row): ?>
                <tr>
                    <td><?= date('m-d H:i', strtotime($row['timestamp'])) ?></td>
                    <td><?= htmlspecialchars($row['user_name']) ?></td>
                    <td class="<?= $row['amount'] > 0 ? 'plus' : 'minus' ?>">
                        <?= ($row['amount'] > 0 ? '+' : '') . $row['amount'] ?>
                    </td>
                </tr>
                <?php endforeach; ?>
            </tbody>
        </table>
    </div>
</body>
</html>
