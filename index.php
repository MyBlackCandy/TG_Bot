<?php
// ดึงค่า DATABASE_URL จาก Environment Variable
$db_url = getenv('DATABASE_URL');
$db_conn = parse_url($db_url);
$chat_id = $_GET['c']; // รับค่า Chat ID จาก URL

try {
    $pdo = new PDO("pgsql:" . sprintf(
        "host=%s;port=%s;user=%s;password=%s;dbname=%s",
        $db_conn['host'], $db_conn['port'], $db_conn['user'], $db_conn['pass'], ltrim($db_conn['path'], "/")
    ));

    // ดึงข้อมูลทั้งหมดของกลุ่มนี้
    $stmt = $pdo->prepare("SELECT * FROM history WHERE chat_id = ? ORDER BY timestamp DESC");
    $stmt->execute([$chat_id]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
} catch (Exception $e) {
    die("Error connecting to database.");
}
?>

<!DOCTYPE html>
<html>
<head>
    <title>账单明细 (รายงานบัญชี)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #f4f4f9; padding: 20px; }
        .card { background: #fff; border-radius: 10px; padding: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #5c67f2; color: white; }
        .plus { color: green; font-weight: bold; }
        .minus { color: red; font-weight: bold; }
    </style>
</head>
<body>
    <div class="card">
        <h2>📊 账单明细 (Chat ID: <?php echo htmlspecialchars($chat_id); ?>)</h2>
        <table>
            <tr>
                <th>时间 (เวลา)</th>
                <th>名称 (ชื่อ)</th>
                <th>金额 (จำนวน)</th>
            </tr>
            <?php foreach ($rows as $row): ?>
            <tr>
                <td><?php echo $row['timestamp']; ?></td>
                <td><?php echo htmlspecialchars($row['user_name']); ?></td>
                <td class="<?php echo $row['amount'] > 0 ? 'plus' : 'minus'; ?>">
                    <?php echo ($row['amount'] > 0 ? '+' : '') . $row['amount']; ?>
                </td>
            </tr>
            <?php endforeach; ?>
        </table>
    </div>
</body>
</html>
