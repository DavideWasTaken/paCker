<?php
declare(strict_types=1);
require dirname(__DIR__) . '/php/src/Packer.php';
use paCker\Packer;

// Padding is supplied by the user. Geometric mode checks containment and
// separation; it does not certify support, gravity, friction or insertion paths.
$result = (new Packer($argv[1] ?? null))
    ->addBox(['id'=>'cube', 'width'=>100, 'length'=>100, 'height'=>100, 'quantity'=>1])
    ->addItem(['id'=>'rod', 'width'=>150, 'length'=>8, 'height'=>8, 'rotation'=>'free3d'])
    ->setOptions(['support_mode'=>'geometric', 'clearance'=>1, 'seed'=>42,
        'time_limit_ms'=>200, 'max_candidates'=>200000])
    ->pack();
echo json_encode($result, JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR), "\n";
