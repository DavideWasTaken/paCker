<?php
declare(strict_types=1);
$root = dirname(__DIR__);
if (!is_file($root . '/php/src/Packer.php')) {
    fwrite(STDERR, "FAIL: PHP facade has not been implemented.\n");
    exit(1);
}
require $argv[2] ?? $root . '/php/src/Packer.php';
use paCker\Packer;
function check(bool $condition, string $message): void {
    if (!$condition) { throw new RuntimeException($message); }
}
function fails(callable $call, string $contains): void {
    try { $call(); } catch (Throwable $e) {
        check(str_contains(strtolower($e->getMessage()), strtolower($contains)), 'Unexpected error: ' . $e->getMessage());
        return;
    }
    throw new RuntimeException('Expected failure: ' . $contains);
}
check(class_exists(Packer::class), 'The canonical paCker namespace must load');
check(class_exists(\ObliquePacker\Packer::class), 'The legacy ObliquePacker namespace must remain available');
$binary = $argv[1] ?? $root . '/build/packer' . (PHP_OS_FAMILY === 'Windows' ? '.exe' : '');
$packer = new Packer($binary);
$packer->addBox(['id' => 'box "è"', 'width' => 180, 'length' => 180, 'height' => 30])
    ->addItem(['id' => 'bar', 'width' => 220, 'length' => 30, 'height' => 20], 2)
    ->setOptions(['max_candidates' => 10000, 'time_limit_ms' => 10000]);
$result = $packer->pack();
check($result['status'] === 'complete', 'Packing should complete');
check(count($result['bins']) === 2, 'Both item instances should pack');
check($result['bins'][0]['type_id'] === 'box "è"', 'Unicode IDs should round-trip');
check((new Packer($binary))->pack()['status'] === 'complete', 'Empty request should succeed');
check((new \ObliquePacker\Packer($binary))->pack()['status'] === 'complete', 'Legacy namespace must still run the packing binary');
if (!isset($argv[1])) {
    check((new Packer())->pack()['status'] === 'complete', 'The canonical binary must be the default');
}
foreach ([-1.0, 1.0, 0.0] as $stock) {
    $stockResult = (new Packer($binary))
        ->addBox(['id' => 'stock-box', 'width' => 1, 'length' => 1, 'height' => 1, 'quantity' => $stock])
        ->addItem(['id' => 'stock-item', 'width' => 1, 'length' => 1, 'height' => 1], 2)->pack();
    $expectedBins = $stock === -1.0 ? 2 : (int) $stock;
    check(count($stockResult['bins']) === $expectedBins, 'Integer-valued floating stock must retain its meaning');
    check(count($stockResult['unpacked']) === 2 - $expectedBins, 'Stock must account for all requested instances');
}
$tinyBox = ['id' => 'tiny-box', 'width' => 0.0001, 'length' => 0.0001, 'height' => 0.0001];
$tinyItem = ['id' => 'tiny-item', 'width' => 0.0001, 'length' => 0.0001, 'height' => 0.0001];
$tinyResult = (new Packer($binary))->addBox($tinyBox)->addItem($tinyItem)->pack();
check($tinyResult['status'] === 'complete', 'An exact minimum-size cube must fit');
check(abs($tinyResult['stats']['utilization'] - 1) < 1e-12, 'An exact minimum-size cube fills the bin');
$tinyItem['width'] = $tinyItem['length'] = $tinyItem['height'] = 0.00010005;
$tinyResult = (new Packer($binary))->addBox($tinyBox)->addItem($tinyItem)->pack();
check($tinyResult['status'] === 'partial' && count($tinyResult['unpacked']) === 1,
    'An oversized minimum-scale cube must be reported unpacked');
check($tinyResult['bins'] === [] && $tinyResult['stats']['utilization'] === 0,
    'An oversized minimum-scale cube must not create a bin');
fails(fn() => (new Packer($root . '/does not exist'))->pack(), 'binary');
fails(fn() => (new Packer($binary))->addItem(['id' => 'x'], 0), 'quantity');
fails(fn() => (new Packer($binary))->addItem(['id' => 'x'])->pack(), 'error');
fails(fn() => (new Packer($binary))->setOptions(['seed' => INF])->pack(), 'json');
// PHP itself is a real executable which exits without emitting the CLI protocol.
fails(fn() => (new Packer(PHP_BINARY))->pack(), 'output');
// Use the PHP interpreter as a deliberately incompatible real child process.
// It executes these harmless snippets from stdin, allowing portable watchdog,
// output flood and nonzero-exit tests without shell scripts or mocks.
$slow = ['id' => '<?php usleep(500000); ?>'];
$started = hrtime(true);
fails(fn() => (new Packer(PHP_BINARY, 0.05))->addItem($slow)->pack(), 'timeout');
check((hrtime(true) - $started) / 1e9 < 0.45, 'Timeout should stop the process promptly');
fails(fn() => (new Packer(PHP_BINARY))->addItem(['id' => '<?php exit(7); ?>'])->pack(), 'exit 7');
fails(fn() => (new Packer(PHP_BINARY))->addItem(['id' => "<?php echo str_repeat('x',17000000); ?>"])->pack(), '16 MiB');
fails(fn() => new Packer($binary, 0), 'timeout');
fails(fn() => (new Packer($binary))->setOptions(['unknown' => str_repeat('x', 1048576)])->pack(), '1 MiB');
$directory = sys_get_temp_dir() . '/oblique path & spaces ' . bin2hex(random_bytes(6));
check(mkdir($directory), 'Create path test directory');
$copy = $directory . '/packer & copy' . (PHP_OS_FAMILY === 'Windows' ? '.exe' : '');
try {
    check(copy($binary, $copy), 'Copy binary to path with shell characters');
    if (PHP_OS_FAMILY !== 'Windows') { chmod($copy, 0700); }
    check((new Packer($copy))->pack()['status'] === 'complete', 'Binary path must bypass the shell');
} finally {
    @unlink($copy);
    @rmdir($directory);
}

// Make a real PHP child emit controlled JSON instead of processing stdin. The
// temporary ini is inherited only during these tests, then the environment is restored.
$fakeDirectory = sys_get_temp_dir() . '/oblique-schema-' . bin2hex(random_bytes(6));
check(mkdir($fakeDirectory), 'Create fake protocol directory');
$oldIni = getenv('PHPRC');
$oldResponse = getenv('OBLIQUE_TEST_RESPONSE');
try {
    $prepend = $fakeDirectory . '/emit.php';
    $response = $fakeDirectory . '/response.json';
    file_put_contents($prepend, '<?php echo file_get_contents(getenv("OBLIQUE_TEST_RESPONSE")); exit(0);');
    file_put_contents($fakeDirectory . '/php.ini', 'auto_prepend_file="' . str_replace('\\', '/', $prepend) . '"' . "\n");
    putenv('PHPRC=' . $fakeDirectory);
    putenv('OBLIQUE_TEST_RESPONSE=' . $response);
    $empty = (new Packer($binary))->pack();
    file_put_contents($response, json_encode($empty, JSON_THROW_ON_ERROR));
    check((new Packer(PHP_BINARY))->pack() === $empty, 'Controlled child should emit a valid empty result');
    foreach (['0.1.0', '0.2.0', '0.3.0', '0.3.1', '0.3.2', '0.3.3', '0.4.0', '0.4.1'] as $version) {
        $compatible = $empty;
        $compatible['version'] = $version;
        file_put_contents($response, json_encode($compatible, JSON_THROW_ON_ERROR));
        check((new Packer(PHP_BINARY))->pack() === $compatible, 'Supported protocol versions must remain valid');
    }
    $badResults = [];
    $invalid = $empty; $invalid['version'] = '0.5.0'; $badResults[] = $invalid;
    foreach (['elapsed_ms' => -1, 'candidates' => -1, 'restarts' => 0.5, 'total_cost' => -1, 'utilization' => 999] as $field => $bad) {
        $invalid = $empty; $invalid['stats'][$field] = $bad; $badResults[] = $invalid;
    }
    $invalid = $empty;
    $invalid['bins'][] = ['id' => '', 'type_id' => 'unrequested', 'width' => -1, 'length' => 1,
        'height' => 1, 'max_weight' => -1, 'cost' => -1, 'weight' => -1, 'items' => []];
    $invalid['stats']['box_count'] = 1;
    $badResults[] = $invalid;
    foreach ($badResults as $invalid) {
        file_put_contents($response, json_encode($invalid, JSON_THROW_ON_ERROR));
        fails(fn() => (new Packer(PHP_BINARY))->pack(), 'output');
    }
    $schemaBox = ['id' => 'schema-box', 'width' => 10, 'length' => 10, 'height' => 10, 'max_weight' => 100, 'cost' => 2];
    $schemaItem = ['id' => 'schema-item', 'width' => 2, 'length' => 2, 'height' => 2, 'weight' => 3];
    $schemaResult = (new Packer($binary))->addBox($schemaBox)->addItem($schemaItem)->pack();
    file_put_contents($response, json_encode($schemaResult, JSON_THROW_ON_ERROR));
    check((new Packer(PHP_BINARY))->addBox($schemaBox)->addItem($schemaItem)->pack() === $schemaResult,
        'Controlled child should emit a valid packed result');
    $badResults = [];
    foreach (['id' => '', 'type_id' => 'unrequested', 'width' => -1, 'length' => 11, 'cost' => -1,
        'max_weight' => -1, 'weight' => -1] as $field => $bad) {
        $invalid = $schemaResult; $invalid['bins'][0][$field] = $bad; $badResults[] = $invalid;
    }
    foreach (['width' => -1, 'height' => 0, 'weight' => -1, 'angle' => 180, 'x' => -1, 'instance' => 0.5] as $field => $bad) {
        $invalid = $schemaResult; $invalid['bins'][0]['items'][0][$field] = $bad; $badResults[] = $invalid;
    }
    foreach ($badResults as $invalid) {
        file_put_contents($response, json_encode($invalid, JSON_THROW_ON_ERROR));
        fails(fn() => (new Packer(PHP_BINARY))->addBox($schemaBox)->addItem($schemaItem)->pack(), 'output');
    }
} finally {
    putenv($oldIni === false ? 'PHPRC' : 'PHPRC=' . $oldIni);
    putenv($oldResponse === false ? 'OBLIQUE_TEST_RESPONSE' : 'OBLIQUE_TEST_RESPONSE=' . $oldResponse);
    foreach (['emit.php', 'php.ini', 'response.json'] as $name) { @unlink($fakeDirectory . '/' . $name); }
    @rmdir($fakeDirectory);
}
echo "PHP integration: PASS\n";
