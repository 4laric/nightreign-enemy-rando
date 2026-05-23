// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    RegisterBonfire(1038201960, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1038201960, 1038200960);
    $InitializeEvent(0, 1038202550, 1038201910, 200, 803600);
    $InitializeCommonEvent(0, 90015009, 1038204700, 1038201501, 0, 1);
    $InitializeCommonEvent(0, 90015208, 9328, 1038204700, 9040);
    $InitializeEvent(0, 1038202520);
    $InitializeCommonEvent(0, 90015501, 1038202300, 74960);
    $InitializeCommonEvent(0, 90015150, 1038200290, 73084);
    $InitializeCommonEvent(0, 90015151, 1038200290, 74044);
    $InitializeCommonEvent(0, 90015152, 1038200290, 74044);
    $InitializeCommonEvent(0, 90015150, 1038200291, 73085);
    $InitializeCommonEvent(0, 90015151, 1038200291, 74045);
    $InitializeCommonEvent(0, 90015152, 1038200291, 74045);
    if (920910 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 1038200800, 904770000, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 1038200800, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1038200800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 1038200800, 904770000, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 1038200800, 30, 920910, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1038202800, 1038200800, 1020, 920910, 11200, 904770000, 1038200800);
    $InitializeCommonEvent(0, 90015006, 1038201500, 1038200500, 1038202800, 5);
    $InitializeCommonEvent(0, 90015005, 1038201500, 1038202800, 1038202800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 920910 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1038202800, 940000, 1038200800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 1038202800, 920910, 1038200800, 0, 0);
S2:
    $InitializeCommonEvent(0, 90015017, 1038200800, 25, 0, 1038202800, 72448, 1038202800);
    $InitializeCommonEvent(0, 90015041, 310, 0, 0, 72479);
    $InitializeCommonEvent(1, 91005503, 1038201551);
    $InitializeEvent(0, 1038202501);
    $InitializeEvent(0, 1038202206);
});

$Event(200, Default, function() {
    $InitializeEvent(0, 1238202500);
});

$Event(1238202500, Default, function() {
    DisableNetworkSync();
    if (EventFlag(8191)) {
        EndEvent();
    }
L0:
    WaitFor(EventFlag(8190));
    ForceAnimationPlayback(1238201600, 1, false, false, false);
    PlaySE(1238202300, SoundType.EnvironmentalSound, 602000000);
    WaitFor(ElapsedSeconds(2));
    SpawnOneshotSFX(TargetEntityType.Area, 1238202510, -1, 807241);
    SpawnOneshotSFX(TargetEntityType.Area, 1238202510, -1, 807240);
    WaitFor(ElapsedSeconds(2));
    SetNetworkconnectedEventFlagID(8191, ON);
});

$Event(1038202501, Default, function() {
    DisableNetworkSync();
    if (EventFlag(8191)) {
        ForceAnimationPlayback(1038201300, 3, true, false, false);
        EndEvent();
    }
L0:
    WaitFor(EventFlag(8191));
    ForceAnimationPlayback(1038201300, 10, false, true, false);
    ForceAnimationPlayback(1038201300, 3, true, false, false);
});

$Event(1038202206, Restart, function() {
    DisableAsset(1038206500);
});

$Event(1038202550, Restart, function(entityId, dummypolyId, sfxId) {
    SpawnOneshotSFX(TargetEntityType.Asset, entityId, dummypolyId, sfxId);
});

$Event(1038202520, Default, function() {
    DisableNetworkSync();
    EndIf(EventFlag(1038204700));
    WaitFor(EventFlag(1038204700));
    ForceAnimationPlayback(20000, 60071, false, false, false);
    SetSpEffect(20000, 99270);
});
