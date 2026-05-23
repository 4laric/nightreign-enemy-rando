// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    RegisterBonfire(1042361950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1042361950, 1042360950);
    $InitializeCommonEvent(0, 90005580, 1042361951, 1042360951, 7650);
    $InitializeCommonEvent(0, 90005910, 1042361800, 7675);
    $InitializeCommonEvent(0, 91005505, 1042362500, 7675);
    $InitializeEvent(0, 1042362200);
    $InitializeEvent(0, 1042362201);
    $InitializeEvent(0, 1042362202);
    $InitializeEvent(0, 1042362203);
    $InitializeCommonEvent(0, 90065901, 1042364890);
    $InitializeCommonEvent(0, 90015150, 1042360200, 73050);
    $InitializeCommonEvent(0, 90015151, 1042360200, 74010);
    $InitializeCommonEvent(0, 90015152, 1042360200, 74010);
    $InitializeCommonEvent(0, 90015150, 1042360201, 73051);
    $InitializeCommonEvent(0, 90015151, 1042360201, 74011);
    $InitializeCommonEvent(0, 90015152, 1042360201, 74011);
    $InitializeCommonEvent(0, 90015150, 1042360202, 73052);
    $InitializeCommonEvent(0, 90015151, 1042360202, 74012);
    $InitializeCommonEvent(0, 90015152, 1042360202, 74012);
    $InitializeCommonEvent(0, 90015150, 1042360203, 73053);
    $InitializeCommonEvent(0, 90015151, 1042360203, 74013);
    $InitializeCommonEvent(0, 90015152, 1042360203, 74013);
    $InitializeCommonEvent(0, 90005931, 1042360200, 1042361211, 0, 1042361212);
    $InitializeCommonEvent(1, 91005503, 1038201200);
    $InitializeCommonEvent(0, 91005503, 1042361220);
    $InitializeCommonEvent(0, 91005503, 1042361221);
    $InitializeCommonEvent(0, 91005503, 1042361222);
    $InitializeCommonEvent(0, 90015140, 1042361200, 200, 9109, 1042368200);
    $InitializeCommonEvent(0, 90015000, 1042362901, 1042360851, 907550002, 30, 756020, 8110);
    $InitializeCommonEvent(0, 99055500, 1042360851, 15);
    $InitializeCommonEvent(0, 90015030, 1042362901, 1042360851, 30, 756020, 8110);
    $InitializeCommonEvent(0, 90015002, 0, 1042362901, 1042360850, 1042360851, 1020, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015160, 1042360850, 1042362901);
    $InitializeCommonEvent(0, 90015161, 1042360850, 1042362900);
    $InitializeCommonEvent(0, 90015162, 1042360850, 1042362900, 1042362901);
    $InitializeCommonEvent(0, 90015163, 1042360851, 1042362900, 1042362901, 1042360850);
    $InitializeCommonEvent(0, 90015164, 1042360850, 1042362901);
    if (MissionActive(202)) {
        $InitializeCommonEvent(0, 90085020, 202, 8356, 8357, 8355, 1042360270, 99850, 1042360270, Hero.Guardian);
        $InitializeCommonEvent(0, 90085035, 202, 8356, 1042360270, 6858, 1042360270, Hero.Guardian);
        $InitializeCommonEvent(0, 90085034, 202, 8355, 8356, 1042360271);
        $InitializeCommonEvent(0, 90085016, 202, 8357, 8356, 1042360270, 1042360271, 1030, 3);
        $InitializeCommonEvent(0, 90015000, 8356, 1042360271, 912000020, 30, 0, 8357);
        $InitializeCommonEvent(0, 99055500, 1042360271, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1042360271, 30, 920930, 8357);
    }
    if (MissionActive(202)) {
        $InitializeCommonEvent(0, 90085030, 202, 1042360275);
        $InitializeCommonEvent(0, 90085030, 202, 1042360276);
        $InitializeCommonEvent(0, 90085030, 202, 1042360277);
    }
    if (MissionActive(401)) {
        $InitializeCommonEvent(0, 90085020, 401, 8401, 8402, 8400, 1042360280, 99852, 1042360280, Hero.Duchess);
        $InitializeCommonEvent(0, 90085021, 401, 8401, 1042362280, 1042360280, Hero.Duchess);
        if (1 == 3) {
            $InitializeCommonEvent(0, 90085002, 401, 8402, 8401, 1042360280, 1042365280, 1042360281, 0, 0, 0, 20032);
        }
        if (2 == 3) {
            $InitializeCommonEvent(0, 90085002, 401, 8402, 8401, 1042360280, 1042365280, 1042360281, 1042360282, 0, 0, 20032);
        }
        if (3 == 3) {
            $InitializeCommonEvent(0, 90085002, 401, 8402, 8401, 1042360280, 1042365280, 1042360281, 1042360282, 1042360283, 0, 20032);
        }
        if (4 == 3) {
            $InitializeCommonEvent(0, 90085002, 401, 8402, 8401, 1042360280, 1042365280, 1042360281, 1042360282, 1042360283, 1042360284, 20032);
        }
        $InitializeCommonEvent(0, 90085016, 401, 8402, 8401, 1042360280, 1042365280, 1030, 3);
        $InitializeCommonEvent(0, 90085022, 401, 8402, 1042362281, 1042360280, 502, Hero.Duchess);
        $InitializeCommonEvent(0, 90085037, 401, 8402, 8400, 1042361280, 9219, Hero.Duchess);
        if (1 == 3) {
            $InitializeCommonEvent(0, 90015000, 8401, 1042360281, 912000040, 30, 0, 8402);
            $InitializeCommonEvent(0, 99055500, 1042360281, 15);
        }
        if (1 != 3) {
            $InitializeCommonEvent(0, 90015000, 8401, 1042365280, 912000040, 30, 0, 8402);
            $InitializeCommonEvent(0, 99055500, 1042365280, 15);
        }
        $InitializeCommonEvent(0, 90015030, 0, 1042365280, 30, 920930, 8402);
    }
    if (MissionActive(401)) {
        $InitializeCommonEvent(0, 90085030, 401, 1042360285);
        $InitializeCommonEvent(0, 90085030, 401, 1042360286);
        $InitializeCommonEvent(0, 90085030, 401, 1042360287);
        $InitializeCommonEvent(0, 90085030, 401, 1042360288);
        $InitializeCommonEvent(0, 90085030, 401, 1042360289);
    }
    $InitializeEvent(0, 1042362910);
    $InitializeCommonEvent(0, 90085001, 801, Hero.Executor, 9257, 9257, 1042361260);
    if (1 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9267, 9257, 9257, 1042365260, 1042360260, 0, 0, 0, 20026);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9267, 9257, 9257, 1042365260, 1042360260, 1042360261, 0, 0, 20026);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9267, 9257, 9257, 1042365260, 1042360260, 1042360261, 1042360262, 0, 20026);
    }
    if (4 == 3) {
        $InitializeCommonEvent(0, 90085002, 801, 9267, 9257, 9257, 1042365260, 1042360260, 1042360261, 1042360262, 1042360263, 20026);
    }
    $InitializeCommonEvent(0, 90085802, 801, 9267, 1042365260);
});

$Event(1042362200, Restart, function() {
    WaitUntilTimeOfDay(10, 0, 0);
    SetNetworkconnectedEventFlagID(1042360900, ON);
});

$Event(1042362201, Restart, function() {
    WaitUntilTimeOfDayInRange(11, 0, 0, 11, 30, 0);
    SetNetworkconnectedEventFlagID(1042360901, ON);
});

$Event(1042362202, Restart, function() {
    WaitFixedTimeRealFrames(12);
    SetNetworkconnectedEventFlagID(1042360902, ON);
});

$Event(1042362203, Restart, function() {
    WaitRandomTimeRealFrames(218103821, 30);
    SetNetworkconnectedEventFlagID(1042360903, ON);
});

$Event(1042362910, Restart, function() {
    WaitFor(SmallBaseAttached(1042372999, 30300000));
    EnableAsset(1042361900);
    EnableAsset(1042361901);
});

$Event(1042362920, Restart, function() {
    WaitFor(MissionActive(401));
    EndIf(EventFlag(1042362930));
    EnableAsset(1042361280);
    ReproduceAssetAnimation(0, 0);
    ReproduceAssetDestruction(0, 0);
    WaitFor(AssetDestroyed(1042361280));
    SetCharacterBackreadState(1042365900, false);
    WaitFor(ElapsedSeconds(1));
    ForceAnimationPlayback(1042360281, 1700, false, false, false);
    WaitFor(ElapsedSeconds(0.2));
    ForceAnimationPlayback(1042360282, 1700, false, false, false);
    WaitFor(ElapsedSeconds(0.2));
    ForceAnimationPlayback(1042360283, 1700, false, false, false);
});

$Event(1042362930, Restart, function() {
    WaitFor(MissionActive(401) && EventFlag(1042362920));
    WaitFor(CharacterDead(1042360281) && CharacterDead(1042360282));
    SetEventFlagID(8400, ON);
});
