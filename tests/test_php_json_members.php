<?php
declare(strict_types=1);
require $argv[1] ?? dirname(__DIR__) . '/php/src/Packer.php';

$members = new ReflectionMethod(\paCker\Packer::class, 'checkJsonMembers');
function membersCheck(bool $condition, string $message): void
{
    if (!$condition) { throw new RuntimeException($message); }
}
function checkMembers(string $json, bool $duplicate = false): void
{
    global $members;
    // The member pass runs after the production JSON decoder's syntax/UTF-8 check.
    json_decode($json, true, 32, JSON_THROW_ON_ERROR);
    try { $members->invoke(null, $json); }
    catch (RuntimeException $error) {
        if ($duplicate && str_contains($error->getMessage(), 'Duplicate')) { return; }
        throw $error;
    }
    membersCheck(!$duplicate, 'A duplicate decoded object key was accepted.');
}

$valid = [
    '{}', '[]', '"braces {} and colon:"',
    '{"id":"{} [] :","nested":[{"id":1},{"id":2}]}',
    '{"01":1,"1":2}', '{"id":{"id":1},"other":{"id":2}}',
    json_encode(['id'=>'quoted "key": value and backslash \\', 'other'=>1], JSON_THROW_ON_ERROR),
    json_encode(['long'=>str_repeat('x', 1000000)], JSON_THROW_ON_ERROR),
    json_encode(['long'=>str_repeat('\\', 600000)], JSON_THROW_ON_ERROR),
];
$duplicates = [
    '{"id":1,"id":2}', '{"id":1,"\u0069d":2}',
    '{"nested":[{"x":1,"x":2}]}', '{"1":1,"\u0031":2}',
    '{"é":1,"\u00e9":2}', '{"😀":1,"\ud83d\ude00":2}',
];
foreach ($valid as $json) { checkMembers($json); }
foreach ($duplicates as $json) { checkMembers($json, true); }

// Low PCRE resources must not turn a valid output into an error or conceal
// duplicates when tokenization fails. Restore every application setting.
$settings = [];
foreach (['pcre.jit', 'pcre.backtrack_limit', 'pcre.recursion_limit'] as $key) {
    $settings[$key] = ini_get($key);
}
try {
    foreach ([['pcre.jit'=>'0', 'pcre.backtrack_limit'=>'1'],
              ['pcre.jit'=>'0', 'pcre.recursion_limit'=>'1']] as $limits) {
        foreach ($settings as $key=>$value) { ini_set($key, $value); }
        foreach ($limits as $key=>$value) { ini_set($key, $value); }
        foreach ($valid as $json) { checkMembers($json); }
        foreach ($duplicates as $json) { checkMembers($json, true); }
    }
} finally {
    foreach ($settings as $key=>$value) { ini_set($key, $value); }
}
foreach ($settings as $key=>$value) { membersCheck(ini_get($key)===$value, 'PCRE setting was not restored: '.$key); }
echo "PHP duplicate members and PCRE fallback: PASS\n";
