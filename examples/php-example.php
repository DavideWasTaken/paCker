<?php
declare(strict_types=1);
require dirname(__DIR__) . '/php/src/Packer.php';

use paCker\Packer;

// All dimensions share one unit (here mm); weights share one unit (here g).
$packer = new Packer(); // Or new Packer('/absolute/path/to/packer').
$result = $packer
    ->addBox(['id' => 'square', 'width' => 180, 'length' => 180, 'height' => 30,
        'max_weight' => 1000, 'cost' => 1, 'quantity' => -1])
    ->addItem(['id' => 'long-bar', 'width' => 220, 'length' => 30, 'height' => 20,
        'weight' => 100, 'rotation' => 'flat', 'diagonal' => true], 2)
    ->setOptions(['angle_step' => 15, 'max_candidates' => 100000, 'time_limit_ms' => 1000])
    ->pack();

echo json_encode($result, JSON_THROW_ON_ERROR | JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), PHP_EOL;
