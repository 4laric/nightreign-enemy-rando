// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1044360282, 15);
    $InitializeCommonEvent(0, 99055500, 1044360283, 15);
    RegisterBonfire(1044361950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1044361950, 1044360950);
    RegisterBonfire(1044361952, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1044361952, 1044360952);
    $InitializeCommonEvent(0, 90005931, 1044360200, 1044361201, 0, 1044361202);
    $InitializeCommonEvent(0, 1044362930, 1044368203, 1044360215);
    $InitializeCommonEvent(1, 1044362930, 1044368204, 1044360216);
    $InitializeCommonEvent(2, 1044362930, 1044368205, 1044360217);
    $InitializeCommonEvent(3, 1044362930, 1044368206, 1044360218);
    $InitializeCommonEvent(0, 90005904, 0, 1044361550, 100, 6101);
    $InitializeCommonEvent(0, 90015140, 1044361210, 200, 9111, 1044368200);
    if (MissionActive(101)) {
        $InitializeCommonEvent(0, 90085020, 101, 8326, 8327, 8325, 1044360280, 99850, 1044360920, Hero.Wylder);
        $InitializeCommonEvent(0, 90085021, 101, 8326, 1044362910, 1044360920, Hero.Wylder);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90085002, 101, 8327, 8326, 1044360920, 1044365910, 1044360281, 0, 0, 0, 20032);
        }
        if (2 == 1) {
            $InitializeCommonEvent(0, 90085002, 101, 8327, 8326, 1044360920, 1044365910, 1044360281, 1044360282, 0, 0, 20032);
        }
        if (3 == 1) {
            $InitializeCommonEvent(0, 90085002, 101, 8327, 8326, 1044360920, 1044365910, 1044360281, 1044360282, 1044360283, 0, 20032);
        }
        if (4 == 1) {
            $InitializeCommonEvent(0, 90085002, 101, 8327, 8326, 1044360920, 1044365910, 1044360281, 1044360282, 1044360283, 1044360284, 20032);
        }
        $InitializeCommonEvent(0, 90085016, 101, 8327, 8326, 1044360920, 1044365910, 1030, 1.5);
        $InitializeCommonEvent(0, 90085022, 101, 8327, 1044362911, 1044360280, 500, Hero.Wylder);
        $InitializeCommonEvent(0, 90085023, 101, 8327, 8325, 1044360280, 6850, 1044360920, Hero.Wylder);
        if (1 == 1) {
            $InitializeCommonEvent(0, 90015000, 8326, 1044360281, 912000000, 30, 0, 8327);
            $InitializeCommonEvent(0, 99055500, 1044360281, 15);
        }
        if (1 != 1) {
            $InitializeCommonEvent(0, 90015000, 8326, 1044365910, 912000000, 30, 0, 8327);
            $InitializeCommonEvent(0, 99055500, 1044365910, 15);
        }
        $InitializeCommonEvent(0, 90015030, 0, 1044365910, 30, 920930, 8327);
    }
    $InitializeEvent(0, 1044362940, 9204, 1044362913);
    $InitializeCommonEvent(0, 90015000, 1044362931, 1044360851, 907550002, 30, 756020, 8110);
    $InitializeCommonEvent(0, 99055500, 1044360851, 15);
    $InitializeCommonEvent(0, 90015030, 1044362931, 1044360851, 30, 756020, 8110);
    $InitializeCommonEvent(0, 90015002, 0, 1044362931, 1044360851, 1044360851, 1020, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015160, 1044360850, 1044362931);
    $InitializeCommonEvent(0, 90015161, 1044360850, 1044362930);
    $InitializeCommonEvent(0, 90015162, 1044360850, 1044362930, 1044362931);
    $InitializeCommonEvent(0, 90015163, 1044360851, 1044362930, 1044362931, 1044360851);
    $InitializeCommonEvent(0, 90015164, 1044360850, 1044362931);
    $InitializeCommonEvent(0, 90015000, 1044362933, 1044360853, 907550002, 30, 756020, 8110);
    $InitializeCommonEvent(0, 99055500, 1044360853, 15);
    $InitializeCommonEvent(0, 90015030, 1044362933, 1044360853, 30, 756020, 8110);
    $InitializeCommonEvent(0, 90015002, 0, 1044362933, 1044360853, 1044360853, 1020, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015160, 1044360852, 1044362933);
    $InitializeCommonEvent(0, 90015161, 1044360852, 1044362932);
    $InitializeCommonEvent(0, 90015162, 1044360852, 1044362932, 1044362933);
    $InitializeCommonEvent(0, 90015163, 1044360853, 1044362932, 1044362933, 1044360853);
    $InitializeCommonEvent(0, 90015164, 1044360852, 1044362933);
    $InitializeCommonEvent(0, 90035075, 1044360220, 1044361211);
    $InitializeCommonEvent(0, 90035076, 1044360220, 1044361212);
    $InitializeCommonEvent(0, 90035077, 1044360220, 1044362800, 1044362801, 1044362802, 1044362803);
    $InitializeCommonEvent(0, 90035077, 1044360220, 1044362804, 1044362805, 1044362806, 1044362807);
    $InitializeCommonEvent(0, 90035077, 1044360220, 1044362808, 1044362809, 1044362810, 1044362811);
    $InitializeCommonEvent(0, 90035078, 1044360220, 1044366900);
    $InitializeCommonEvent(0, 90035079, 1044360220, 1044362700, 1044361211);
    $InitializeCommonEvent(0, 90035070, 0, 0, 1044365200, 1044360220);
    $InitializeCommonEvent(0, 90035085, 1044360220, 1044362710, 6);
    $InitializeCommonEvent(0, 90035080, 1044360220, 1044365920, 1044362890);
    $InitializeCommonEvent(0, 90035081, 1044360220);
    $InitializeCommonEvent(0, 90035082, 1044360220, 1044360210, 1044360220, 1044360221);
    $InitializeCommonEvent(0, 90035083, 1044360220, 1);
    $InitializeCommonEvent(0, 90035083, 1044360220, 2);
    $InitializeCommonEvent(0, 90035083, 1044360220, 3);
    $InitializeCommonEvent(0, 90035084, 1044360220, 1044361211, 1044360210, 1);
    $InitializeCommonEvent(0, 90035084, 1044360220, 1044361211, 1044360220, 2);
    $InitializeCommonEvent(0, 90035084, 1044360220, 1044361211, 1044360221, 3);
    $InitializeCommonEvent(0, 90035087, 1044360220, 1044361211);
    $InitializeCommonEvent(0, 90035088, 1044360220, 1044360214);
    $InitializeCommonEvent(0, 90035088, 1044360220, 1044360222);
    $InitializeCommonEvent(0, 91005504, 1044361500, 7601, 0, 0, 0);
    $InitializeCommonEvent(0, 91005504, 1044361510, 7600, 7602, 7603, 0);
    $InitializeCommonEvent(0, 90015501, 1044362300, 73995);
});

$Event(1044362202, Default, function() {
    ForceAnimationPlayback(1044360490, 30010, true, false, false);
    WaitFor(CharacterHasSpEffect(10000, 8971500) && InArea(10000, 1044362651));
    InvokeEnemyGenerator(1044362650);
    WaitFixedTimeSeconds(1);
    ForceCharacterTreasure(1044360650);
    RestartEvent();
});

$Event(1044362900, Default, function() {
    WaitFor(EventFlag(1044362905));
    SetCharacterBackreadState(1044360900, false);
});

$Event(1044362910, Restart, function() {
    WaitFor(MissionActive(101));
    EndIf(EventFlag(1044362920));
    SetSpEffect(1044360280, 99840);
    WaitFor(ActionButtonInArea(4351, 1044360280));
    ClearSpEffect(1044360280, 99840);
    SetCharacterBackreadState(1044365900, false);
    WaitFor(ElapsedSeconds(1));
    ForceAnimationPlayback(1044360281, 1700, false, false, false);
    WaitFor(ElapsedSeconds(0.2));
    ForceAnimationPlayback(1044360282, 1700, false, false, false);
    WaitFor(ElapsedSeconds(0.2));
    ForceAnimationPlayback(1044360283, 1700, false, false, false);
});

$Event(1044362920, Restart, function() {
    WaitFor(MissionActive(101) && EventFlag(1044362910));
    WaitFor(CharacterDead(1044360281) && CharacterDead(1044360282) && CharacterDead(1044360283));
    SetEventFlagID(8325, ON);
});

$Event(1044362930, Restart, function(eventFlagId, chrEntityId) {
    EndIf(EventFlag(eventFlagId));
    WaitFor(EventFlag(eventFlagId));
    ForceCharacterTreasure(chrEntityId);
});

$Event(1044362940, Default, function(eventFlagId, areaEntityId) {
    DisableNetworkSync();
    EndIf(!MissionActive(101));
    SetEventFlagID(eventFlagId, OFF);
    WaitFor(InArea(20000, areaEntityId));
    SetEventFlagID(eventFlagId, ON);
    WaitFor(!InArea(20000, areaEntityId));
    SetEventFlagID(eventFlagId, OFF);
    RestartEvent();
});
