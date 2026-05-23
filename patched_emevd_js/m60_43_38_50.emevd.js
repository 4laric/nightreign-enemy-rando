// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90005933, 1043380200, 9890, 9890);
    $InitializeCommonEvent(0, 91005506, 1043385200);
    $InitializeEvent(0, 1043382950, 1043382590, 1043382580, 0, 0);
    RegisterBonfire(1043381950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1043381950, 1043380950);
    RegisterBonfire(1043381951, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1043381951, 1043380951);
    $InitializeCommonEvent(0, 90005580, 1043381952, 1043380952, 7656);
    $InitializeCommonEvent(0, 90005910, 1043381800, 7681);
    $InitializeCommonEvent(0, 91005505, 1043382570, 7681);
    $InitializeCommonEvent(0, 90065901, 1043384890);
    $InitializeCommonEvent(0, 90015150, 1043380200, 73064);
    $InitializeCommonEvent(0, 90015151, 1043380200, 74024);
    $InitializeCommonEvent(0, 90015152, 1043380200, 74024);
    $InitializeCommonEvent(0, 90015150, 1043380201, 73065);
    $InitializeCommonEvent(0, 90015151, 1043380201, 74025);
    $InitializeCommonEvent(0, 90015152, 1043380201, 74025);
    $InitializeCommonEvent(0, 90005200, 1043380300, 30000, 20000, 1043382300, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005931, 1043380240, 1043381240, 0, 1043381241);
    $InitializeCommonEvent(0, 91005503, 1043381500);
    $InitializeCommonEvent(0, 90015140, 1043381200, 200, 9105, 1043388200);
    $InitializeEvent(0, 1043382810, 1043382550);
    $InitializeEvent(0, 1043382800, 1043382560);
    $InitializeCommonEvent(0, 90015000, 1043382901, 1043380851, 907550002, 30, 756020, 8110);
    $InitializeCommonEvent(0, 99055500, 1043380851, 15);
    $InitializeCommonEvent(0, 90015030, 1043382901, 1043380851, 30, 756020, 8110);
    $InitializeCommonEvent(0, 90015002, 0, 1043382901, 1043380850, 1043380851, 1020, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015160, 1043380850, 1043382901);
    $InitializeCommonEvent(0, 90015161, 1043380850, 1043382900);
    $InitializeCommonEvent(0, 90015162, 1043380850, 1043382900, 1043382901);
    $InitializeCommonEvent(0, 90015163, 1043380851, 1043382900, 1043382901, 1043380850);
    $InitializeCommonEvent(0, 90015164, 1043380850, 1043382901);
    $InitializeCommonEvent(0, 90085612, 602, Hero.Revenant, 9244, 9224, 1043380280, 8459);
    if (1 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9234, 9224, 9224, 1043385280, 1043380281, 0, 0, 0, 20026);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9234, 9224, 9224, 1043385280, 1043380281, 1043380282, 0, 0, 20026);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9234, 9224, 9224, 1043385280, 1043380281, 1043380282, 1043380283, 0, 20026);
    }
    if (4 == 3) {
        $InitializeCommonEvent(0, 90085002, 602, 9234, 9224, 9224, 1043385280, 1043380281, 1043380282, 1043380283, 1043380284, 20026);
    }
    $InitializeCommonEvent(0, 90085613, 602, 9234, 9224, 9224, 1043385280);
    $InitializeCommonEvent(0, 90085614, 602, 9234, 1043386280, 1043380280, 8459);
    $InitializeCommonEvent(0, 90015501, 1043382300, 73993);
});

$Event(1043382800, Restart, function(areaEntityId) {
    DisableNetworkSync();
    WaitFor(InArea(20000, areaEntityId));
    SetSpEffect(20000, 99216);
    RestartEvent();
});

$Event(1043382810, Restart, function(areaEntityId) {
    DisableNetworkSync();
    WaitFor(InArea(20000, areaEntityId));
    SetSpEffect(20000, 99218);
    RestartEvent();
});

$Event(1043382950, Restart, function(areaEntityId, entityId, eventFlagId, eventFlagId2) {
    DisableNetworkSync();
    EndIf(!PlayerIsInOwnWorld());
    EndIf(!EventFlag(6011));
    SetEventFlagID(1044394200, OFF);
    if (eventFlagId2 != 0) {
        flagArea &= EventFlag(eventFlagId2);
    }
    flagArea &= !EventFlag(eventFlagId) && InArea(20000, areaEntityId);
    WaitFor(flagArea);
    SetEventFlagID(1044394200, ON);
    WarpCharacterAndCopyFloorWithFadeout(20000, TargetEntityType.Area, entityId, -1, 0, false, true);
    WaitFixedTimeFrames(30);
    SetEventFlagID(1044394200, OFF);
    WaitFixedTimeFrames(1);
    RestartEvent();
});
