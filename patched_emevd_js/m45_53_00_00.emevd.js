// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015000, 45530200, 45530800, 907520001, 30, 0, 8062);
    $InitializeCommonEvent(0, 99055500, 45530800, 15);
    $InitializeCommonEvent(0, 90015030, 45530200, 45530800, 30, 752020, 8062);
    $InitializeCommonEvent(0, 90015002, 8078, 45530200, 45530800, 45530800, 1020, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90035230, 45530800, 45530200, 8060, 150, 300);
    $InitializeCommonEvent(0, 90035230, 45530800, 45530200, 8100, 150, 500);
    $InitializeCommonEvent(0, 90035231, 45530800, 45530200, 8101);
    $InitializeCommonEvent(0, 90035232, 45530800, 45535810, 45530810, 45530811, 45530812, 45530200);
    $InitializeCommonEvent(0, 90035233, 45530800, 45530810, 45530811, 45530812, 45530200);
    $InitializeCommonEvent(0, 90035234, 45530800, 45535810, 45530200);
    $InitializeCommonEvent(0, 90035235, 45534200, 45530200);
    $InitializeCommonEvent(0, 90035236, 45530800, 45535810, 45530800, 45530200);
    $InitializeCommonEvent(0, 90035237, 45534200, 45534201, 45530200);
    $InitializeCommonEvent(0, 90035238, 45530200, 45530800, 45530810, 45530811, 45530812);
});

$Event(45530900, Default, function() {
    WaitFor(EventFlag(45530905));
    ShootBullet(45530810, 20000, -1, 201200090, 0, 0, 0);
    WaitFor(ElapsedFrames(1));
    SetEventFlagID(45530905, OFF);
    WaitFor(ElapsedFrames(1));
    RestartEvent();
});

$Event(45530910, Default, function() {
    WaitFor(EventFlag(45530915));
    ShootBullet(45530810, 45530810, -1, 201200095, 0, 0, 0);
    WaitFor(ElapsedFrames(1));
    SetEventFlagID(45530915, OFF);
    WaitFor(ElapsedFrames(1));
    RestartEvent();
});

$Event(45530920, Default, function() {
    WaitFor(EventFlag(45530925));
    ShootBullet(45530810, 20000, -1, 201200080, 0, 0, 0);
    WaitFor(ElapsedFrames(1));
    SetEventFlagID(45530925, OFF);
    WaitFor(ElapsedFrames(1));
    RestartEvent();
});

$Event(45530930, Default, function() {
    WaitFor(EventFlag(45530935));
    ShootBullet(45530810, 20000, -1, 201200081, 0, 0, 0);
    WaitFor(ElapsedFrames(1));
    SetEventFlagID(45530935, OFF);
    WaitFor(ElapsedFrames(1));
    RestartEvent();
});

$Event(45530940, Default, function() {
    WaitFor(EventFlag(45530945));
    ShootBullet(45530810, 20000, -1, 201200082, 0, 0, 0);
    WaitFor(ElapsedFrames(1));
    SetEventFlagID(45530945, OFF);
    WaitFor(ElapsedFrames(1));
    RestartEvent();
});

$Event(45530990, Default, function() {
    WaitFor(EventFlag(45530995));
    SetCharacterEventTarget(45530810, 20000);
    WaitFor(ElapsedFrames(1));
    ShootBullet(45530810, 20000, -1, 201200095, 0, 0, 0);
    WaitFor(ElapsedSeconds(0.5));
    ShootBullet(45530810, 20000, -1, 201200090, 0, 0, 0);
    SetEventFlagID(45530995, OFF);
    WaitFor(ElapsedFrames(1));
    RestartEvent();
});

$Event(45530991, Default, function() {
    WaitFor(EventFlag(45530996));
    ShootBullet(45530810, 20000, -1, 201200080, 0, 0, 0);
    WaitFor(ElapsedSeconds(0.5));
    SetCharacterEventTarget(45530810, 45530800);
    WaitFor(ElapsedFrames(1));
    IssueShortWarpRequest(45530810, TargetEntityType.Character, 20000, 210);
    WaitFor(ElapsedSeconds(2));
    ShootBullet(45530810, 45530810, -1, 201200090, 0, 0, 0);
    SetEventFlagID(45530996, OFF);
    WaitFor(ElapsedFrames(1));
    RestartEvent();
});
