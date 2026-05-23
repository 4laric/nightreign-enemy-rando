// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 30300050, 30300051, 1, 30300200, 30300202, 30300203, 30302405, 30302406, 30302407, 0, 1, 2, 30302415, 30302416, 30302417, 30302420, 30302421, 30302422, 30302400);
    $InitializeCommonEvent(0, 90015301, 30305300, 30300200, 30300201, 30300202, 30300203, 1);
    $InitializeCommonEvent(0, 90015306, 30306500);
    $InitializeCommonEvent(0, 90015303, 30302401);
    $InitializeCommonEvent(0, 90015305, 30302430, 30302431, 30302432, 30302433);
    $InitializeCommonEvent(0, 90015304, 30300050, 30300200, 30300202);
    if (1 >= 2) {
        $InitializeCommonEvent(0, 90015304, 30300051, 30300200, 30300203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 30300800, 30302800, 30, 904660310, 0, 0);
        $InitializeCommonEvent(0, 99055500, 30300800, 15);
        $InitializeCommonEvent(0, 90015031, 0, 30300800, 30302800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 30300800, 30302800, 30, 904660310, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 30300800, 30302800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 30300800, 30300800, 1030, 940000, 11200, 904660310, 30300800);
    $InitializeCommonEvent(0, 90015006, 30301500, 30300500, 30300800, 5);
    $InitializeCommonEvent(0, 90015005, 30301500, 30302800, 30300800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 30300800, 940000, 30300800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 30300800, 940000, 30300800, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 30300800, 8160);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 30305810, 30302810, 30, 903350323, 0, 0);
        $InitializeCommonEvent(0, 99055500, 30305810, 15);
        $InitializeCommonEvent(0, 90015031, 0, 30305810, 30302810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 30305810, 30302810, 30, 903350323, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 30305810, 30302810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 30300810, 30305810, 1030, 940000, 11200, 903350323, 30300510);
    $InitializeCommonEvent(0, 90015006, 30301510, 30300510, 30300810, 5);
    $InitializeCommonEvent(0, 90015005, 30301510, 30302810, 30300810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 30300810, 940000, 30305810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 30300810, 940000, 30305810, 0, 0);
S5:
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 30300810, 8160);
    }
    $InitializeCommonEvent(0, 90035280, 30302491, 30300700, 30300701, 30300702, 8060, 0, 30300800, 30300810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 30302491, 30300700, 30300701, 30300702, 80010, 0, 30300800, 30300810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 30302491, 30300700, 30300701, 30300702, 80011, 1, 30300800, 30300810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035281, 30302491, 30300700, 30300701, 30300702, 80011, 30300800, 30300810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035282, 30300490, 30302490, 30300700, 30300701, 30300702, 30300703);
    $InitializeCommonEvent(0, 90035283, 30300490, 30302491, 30301690, 30300700, 30300701, 30300702, 30300704, 30300705, 30300706);
    $InitializeCommonEvent(0, 90035284, 30305490, 30305491, 30300700, 30300702, 30300705, 30300706);
    $InitializeCommonEvent(0, 90035285, 30300490, 30300700, 30300701, 30300702, 30300705, 30300706);
    $InitializeCommonEvent(0, 90035286, 30300490, 30302491, 30300700, 30300701, 30300702, 30300705, 30300706);
    $InitializeCommonEvent(0, 90035288, 30302491, 30300700, 30300702, 30300705, 30300706);
    $InitializeCommonEvent(0, 90015000, 30300704, 30300490, 907640001, 50, 0, 30300706);
    $InitializeCommonEvent(0, 99055500, 30300490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 30300704, 30300705, 30300490, 1020, 0, -1, -1, 30300490, 0);
    $InitializeEvent(0, 30302700);
    $InitializeEvent(0, 30302710, 30301210, 30302510, 30301211);
    $InitializeEvent(1, 30302710, 30301211, 30302511, 30301210);
    $InitializeEvent(0, 30302900, 30300800);
    $InitializeEvent(0, 30302910, 30300800);
    $InitializeEvent(0, 30302500);
    $InitializeEvent(0, 30302501);
    $InitializeEvent(0, 30302630, 30305200, 30302210);
    $InitializeEvent(1, 30302630, 30305201, 30302211);
    $InitializeEvent(2, 30302630, 30305202, 30302800);
    $InitializeEvent(3, 30302630, 30305210, 30302220);
    $InitializeEvent(4, 30302630, 30305211, 30302221);
    $InitializeEvent(5, 30302630, 30305212, 30302222);
    $InitializeCommonEvent(0, 90005915, 30301600, 30308000, 90040, 300);
    $InitializeCommonEvent(0, 90015009, 30308000, 30301600, 0, 0);
    $InitializeCommonEvent(1, 90015009, 30308000, 30301600, 1, 0);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 30300800);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 30300810);
});

$Event(30302700, Restart, function() {
    if (EventFlag(30302711)) {
        ForceAnimationPlayback(30301200, 10, true, false, false);
        ForceAnimationPlayback(30301201, 10, true, false, false);
        EndEvent();
    }
    if (EventFlag(30300210)) {
        ForceAnimationPlayback(30301200, 11, true, false, false);
        ForceAnimationPlayback(30301201, 11, true, false, false);
        WaitFor(ElapsedSeconds(6));
        SetNetworkconnectedEventFlagID(30300211, ON);
        EndEvent();
    }
    WaitFor(EventFlag(30300210));
    ForceAnimationPlayback(30301200, 11, true, false, false);
    ForceAnimationPlayback(30301201, 11, true, false, false);
    WaitFor(ElapsedSeconds(6));
    SetNetworkconnectedEventFlagID(30300211, ON);
});

$Event(30302710, Restart, function(entityId, areaEntityId, entityId2) {
    if (!EventFlag(30300210)) {
        WaitFor(InArea(20000, areaEntityId));
        EndIf(EventFlag(30300210));
        ForceAnimationPlayback(entityId, 1, false, false, false);
        ForceAnimationPlayback(entityId2, 1, false, true, false);
        SetNetworkconnectedEventFlagID(30300210, ON);
    }
    ForceAnimationPlayback(entityId, 2, true, false, false);
    ForceAnimationPlayback(entityId2, 2, true, false, false);
});

$Event(30302500, Restart, function() {
    EnableCharacterDefaultBackread(30300300);
    SetCharacterEnableDistance(30300300, 230);
    DisableCharacterDisableOnHitUnload(30300300);
    EnableDistancebasedNetworkUpdateAuthority(30300300);
    DisableCharacterGravity(30300300);
});

$Event(30302501, Restart, function() {
    EndIf(EventFlag(30300810));
    if (!EventFlag(30303250)) {
        WaitFor(
            (InArea(10002, 30302200)
                || InArea(10003, 30302200)
                || InArea(10004, 30302200)
                || EventFlag(30300810))
                && PlayAreaCurrentTimeInRange(0, 0, 0, 23, 58, 59)
                && !EventFlag(7515));
        EndIf(EventFlag(30300810));
        ClearCharactersAITarget(30300300);
        if (InArea(10002, 30302200)) {
            SetCharacterEventTarget(30300300, 10002);
        } else if (InArea(10003, 30302200)) {
            SetCharacterEventTarget(30300300, 10003);
        } else if (InArea(10004, 30302200)) {
            SetCharacterEventTarget(30300300, 10004);
            Goto(L0);
        }
L0:
        WaitFor(ElapsedSeconds(0.5));
        ShootBulletUnknown2003125(30300300, 30301300, 90, 802600000, true, 0, 0, 0);
        SetNetworkconnectedEventFlagID(30303250, ON);
    }
L1:
    WaitFor(ElapsedSeconds(4.3));
    SetNetworkconnectedEventFlagID(30303250, OFF);
    RestartEvent();
});

$Event(30302600, Restart, function(entityId, areaEntityId, eventFlagId, timeFrames) {
    EnableNetworkSync();
    WaitFor(InArea(20000, areaEntityId) && EventFlag(eventFlagId) && EventFlag(30303254) && cond);
    EndIf(EventFlag(30300810));
    WaitFixedTimeFrames(timeFrames);
    ShootBullet(30300300, entityId, 90, 802600000, 0, 0, 0);
    SetNetworkconnectedEventFlagID(eventFlagId, OFF);
    SetNetworkconnectedEventFlagID(30303254, OFF);
    WaitFixedTimeSeconds(1);
    RestartEvent();
L1:
    WaitFixedTimeSeconds(1);
    RestartEvent();
});

$Event(30302610, Restart, function(timeSeconds, eventFlagId) {
    EndIf(!PlayerIsInOwnWorld());
    DisableNetworkSync();
    EndIf(EventFlag(30300810));
    WaitFor(!EventFlag(eventFlagId));
    WaitFixedTimeSeconds(timeSeconds);
    SetNetworkconnectedEventFlagID(eventFlagId, ON);
    WaitFixedTimeFrames(1);
    RestartEvent();
});

$Event(30302620, Restart, function(chrEntityId) {
    EnableNetworkSync();
    EnableCharacterDefaultBackread(chrEntityId);
    SetCharacterEnableDistance(chrEntityId, 230);
    DisableCharacterDisableOnHitUnload(chrEntityId);
    EnableDistancebasedNetworkUpdateAuthority(chrEntityId);
    DisableCharacterGravity(chrEntityId);
});

$Event(30302630, Restart, function(chrEntityId, areaEntityId) {
    WaitFor(ElapsedSeconds(1));
    SetSpEffect(chrEntityId, 8081);
    WaitFor(InArea(20000, areaEntityId));
    ClearSpEffect(chrEntityId, 8081);
    WaitFor(!InArea(20000, areaEntityId));
    RestartEvent();
});

$Event(30302900, Restart, function(chrEntityId) {
    WaitFor(PlayAreaCurrentTime(23, 30));
    WaitFor(ElapsedSeconds(5));
    DisableCharacterAI(chrEntityId);
    WaitFor(ElapsedFrames(1));
    ClearCharactersAITarget(chrEntityId);
    RequestCharacterAIReplan(chrEntityId);
    ForceAnimationPlayback(chrEntityId, 0, false, false, false);
    WaitFor(InsidePlayArea(chrEntityId, 0));
    EnableCharacterAI(chrEntityId);
    RestartEvent();
});

$Event(30302910, Default, function(chrEntityId) {
    WaitFor(CharacterHasSpEffect(20000, 99210));
    DisableCharacterAI(chrEntityId);
    WaitFor(ElapsedFrames(1));
    ClearCharactersAITarget(chrEntityId);
    RequestCharacterAIReplan(chrEntityId);
    ForceAnimationPlayback(chrEntityId, 0, false, false, false);
    WaitFor(!CharacterHasSpEffect(20000, 99210));
    WaitFor(ElapsedSeconds(5));
    EnableCharacterAI(chrEntityId);
});
