<?php
declare(strict_types=1);
require dirname(__DIR__) . '/php/src/Packer.php';
use paCker\Packer;
function check3(bool $ok, string $message): void { if (!$ok) { throw new RuntimeException($message); } }
function reject3(callable $call): void {
    try { $call(); } catch (RuntimeException $e) { return; }
    throw new RuntimeException('Invalid schema 2 result was accepted.');
}
$binary = $argv[1] ?? dirname(__DIR__) . '/build/packer' . (PHP_OS_FAMILY === 'Windows' ? '.exe' : '');
$box = ['id'=>'b', 'width'=>100, 'length'=>100, 'height'=>100, 'quantity'=>1];
$item = ['id'=>'rod', 'width'=>150, 'length'=>8, 'height'=>8, 'rotation'=>'free3d'];
$options = ['support_mode'=>'geometric', 'time_limit_ms'=>10000, 'max_candidates'=>4000, 'restarts'=>1];
$packer = (new Packer($binary))->addBox($box)->addItem($item)->setOptions($options);
$result = $packer->pack();
check3($result['schema_version'] === 2 && $result['status'] === 'complete', '3D rod must pack through PHP.');
$validate = new ReflectionMethod(Packer::class, 'validateResult');
$validate->invoke($packer, $result);
$precision=ini_set('serialize_precision','12');
try {
    $decimalResult=(new Packer($binary))->addBox(['id'=>'d','width'=>2,'length'=>2,'height'=>2])
        ->addItem(['id'=>'d','width'=>0.12345678901234566,'length'=>0.23456789012345678,'height'=>0.3456789012345679,'rotation'=>'none'])
        ->setOptions(['support_mode'=>'geometric'])->pack();
    check3($decimalResult['bins'][0]['items'][0]['width']===0.12345678901234566,'PHP request doubles must round-trip.');
    check3(ini_get('serialize_precision')==='12','Facade must restore caller JSON precision.');
} finally { ini_set('serialize_precision',$precision); }
$bad = [];
foreach (['schema_version'=>1, 'support_mode'=>'full_base', 'clearance'=>1, 'version'=>'made-up'] as $field=>$value) {
    $r=$result; $r[$field]=$value; $bad[]=$r;
}
foreach (['center'=>[0,0,0], 'width'=>149, 'instance'=>1] as $field=>$value) {
    $r=$result; $r['bins'][0]['items'][0][$field]=$value; $bad[]=$r;
}
foreach ([[INF,0,0,1], [0,0,0,2], [0,0,0,-1], [0,0,1], [0,0,0,0]] as $q) {
    $r=$result; $r['bins'][0]['items'][0]['orientation']=$q; $bad[]=$r;
}
foreach ([[INF,0,0], [NAN,0,0], [0,0], ['0',0,0]] as $center) {
    $r=$result; $r['bins'][0]['items'][0]['center']=$center; $bad[]=$r;
}
foreach (['seed'=>43, 'stop_reason'=>'other', 'candidates'=>4001, 'xy_candidates'=>4001,
          'xy_elapsed_ms'=>1e8, 'box_count'=>0, 'total_cost'=>2, 'utilization'=>0, 'restarts'=>2] as $field=>$value) {
    $r=$result; $r['stats'][$field]=$value; $bad[]=$r;
}
$r=$result; $r['stats']['options']['clearance']=1; $bad[]=$r;
$r=$result; $r['bins'][0]['items'][]=$r['bins'][0]['items'][0]; $bad[]=$r;
$r=$result; $r['bins'][0]['items'][0]['angle']=0; $bad[]=$r;
$r=$result; $r['unpacked'][]=['id'=>'rod','instance'=>0]; $r['status']='partial'; $bad[]=$r;
foreach ($bad as $r) { reject3(fn()=>$validate->invoke($packer,$r)); }
reject3(fn()=>$validate->invoke(new Packer($binary),$result));
reject3(fn()=>$validate->invoke($packer, (new Packer($binary))->pack()));
foreach ([0, 0.1] as $margin) {
    $p=(new Packer($binary))->addBox(['id'=>'b','width'=>1,'length'=>1,'height'=>1,'quantity'=>1])
        ->addItem(['id'=>'i','width'=>1,'length'=>1,'height'=>1,'rotation'=>'none'],2)
        ->setOptions(['support_mode'=>'geometric','clearance'=>$margin]);
    $r=$p->pack();
    check3(count($r['bins'])===($margin===0?1:0), 'Margin/stock must be enforced.');
    check3(count($r['unpacked'])===($margin===0?1:2), 'All unpacked instances must remain.');
}
check3((new Packer($binary))->setOptions(['support_mode'=>'geometric'])->pack()['status']==='complete','Empty geometric order.');
$partial=(new Packer($binary))->addItem($item)->setOptions($options)->pack();
check3(count($partial['unpacked'])===1 && $partial['bins']===[], 'Zero boxes must be partial.');
$zeroBox=['id'=>'zero','width'=>1,'length'=>1,'height'=>1,'max_weight'=>0];
$zeroItem=['id'=>'weight','width'=>1,'length'=>1,'height'=>1,'rotation'=>'none'];
$zeroResult=(new Packer($binary))->addBox($zeroBox)->addItem($zeroItem)->setOptions(['support_mode'=>'geometric'])->pack();
$zeroResult['bins'][0]['weight']=$zeroResult['bins'][0]['items'][0]['weight']=1e-8;
$zeroItem['weight']=1e-8;
$zeroPacker=(new Packer($binary))->addBox($zeroBox)->addItem($zeroItem)->setOptions(['support_mode'=>'geometric']);
reject3(fn()=>$validate->invoke($zeroPacker,$zeroResult));
$pairBox=['id'=>'pair','width'=>3,'length'=>2,'height'=>2];
$pairItem=['id'=>'pair','width'=>1,'length'=>1,'height'=>1,'rotation'=>'none'];
$pairPacker=(new Packer($binary))->addBox($pairBox)->addItem($pairItem,2)->setOptions(['support_mode'=>'geometric','clearance'=>0.1]);
$pair=$pairPacker->pack();
check3(count($pair['bins'])===1 && count($pair['bins'][0]['items'])===2,'Pair clearance must pack and validate.');
$pair['bins'][0]['items'][1]['center']=$pair['bins'][0]['items'][0]['center'];
reject3(fn()=>$validate->invoke($pairPacker,$pair));
$jsonMembers=new ReflectionMethod(Packer::class,'checkJsonMembers');
$jsonMembers->invoke(null,'{"id":"commas, colons: and braces {}", "nested":[{"id":1}]}');
reject3(fn()=>$jsonMembers->invoke(null,'{"id":1,"\\u0069d":2}'));
// The exact shared local-to-world convention is exercised through the same
// helper used by result validation, without Python or an external service.
$vertices = new ReflectionMethod(Packer::class, 'geometricVertices');
$fixtures=json_decode(file_get_contents(__DIR__.'/fixtures/poses3d.json'),true,32,JSON_THROW_ON_ERROR);
foreach ($fixtures['poses'] as $fixture) {
    $actual=$vertices->invoke(null,$fixture['pose']);
    foreach ($fixture['vertices'] as $i=>$v) {
        foreach ($v as $j=>$value) { check3(abs($actual[$i][$j]-$value)<1e-12,'Quaternion fixture: '.$fixture['name']); }
    }
}
$weightFailures=[];
foreach ([[100000000000,100000000000.00002,1], [1e12,500000000000.00006,2]] as [$capacity,$weight,$quantity]) {
    $weightBox=['id'=>'boundary','width'=>$quantity,'length'=>1,'height'=>1,'max_weight'=>$capacity,'quantity'=>1];
    $weightItem=['id'=>'boundary','width'=>1,'length'=>1,'height'=>1,'weight'=>$weight,'rotation'=>'none'];
    $weightPacker=(new Packer($binary))->addBox($weightBox)->addItem($weightItem,$quantity)->setOptions(['support_mode'=>'geometric']);
    try { $boundary=$weightPacker->pack(); }
    catch (RuntimeException $e) { $weightFailures[]=$capacity.': '.$e->getMessage(); continue; }
    check3($boundary['status']==='complete' && $boundary['bins'][0]['weight']>$capacity,'Relative weight allowance must remain accepted.');
    $weightItem['weight']+=0.01;
    $overweight=(new Packer($binary))->addBox($weightBox)->addItem($weightItem,$quantity)->setOptions(['support_mode'=>'geometric']);
    check3($overweight->pack()['status']==='partial','Actual overweight must remain unpacked.');
    foreach ($boundary['bins'][0]['items'] as &$placed) { $placed['weight']+=0.01; }
    unset($placed);
    $boundary['bins'][0]['weight']=array_sum(array_column($boundary['bins'][0]['items'],'weight'));
    reject3(fn()=>$validate->invoke($overweight,$boundary));
}
check3($weightFailures===[],'Valid weight boundaries rejected: '.implode('; ',$weightFailures));
echo "PHP schema 2 integration: PASS\n";
