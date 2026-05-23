// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 30000050, 30000051, 1, 30000200, 30000202, 30000203, 0, 1, 2, 0, 1, 2, 30002415, 30002416, 30002417, 30002420, 30002421, 30002422, 30002400);
    $InitializeCommonEvent(0, 90015301, 30005300, 30000200, 30000201, 30000202, 30000203, 1);
    $InitializeCommonEvent(0, 90015306, 30006500);
    $InitializeCommonEvent(0, 90015303, 30002401);
    $InitializeCommonEvent(0, 90015305, 30002430, 30002431, 30002432, 30002433);
    $InitializeCommonEvent(0, 90015304, 30000050, 30000200, 30000202);
    if (1 >= 2) {
        $InitializeCommonEvent(0, 90015304, 30000051, 30000200, 30000203);
    }
    $InitializeEvent(0, 30002900);
    $InitializeCommonEvent(0, 90005915, 30001600, 30008000, 90040, 300);
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 30000800, 904311000, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 30000800, 15);
        $InitializeCommonEvent(0, 90015030, 0, 30000800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 30000800, 904311000, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 30000800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 30000800, 30000800, 1030, 940000, 11200, 904311000, 30000800);
    $InitializeCommonEvent(0, 90015006, 30001500, 30000500, 30000800, 5);
    $InitializeCommonEvent(0, 90015005, 30001500, 30002800, 30000800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 30000800, 940000, 30000800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 30000800, 940000, 30000800, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 30000800, 8160);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 30000810, 30002810, 30, 904470000, 0, 0);
        $InitializeCommonEvent(0, 99055500, 30000810, 15);
        $InitializeCommonEvent(0, 90015031, 0, 30000810, 30002810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 30000810, 30002810, 30, 904470000, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 30000810, 30002810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 30000810, 30000810, 1030, 940000, 11200, 904470000, 30000810);
    $InitializeCommonEvent(0, 90015006, 30001510, 30000510, 30000810, 5);
    $InitializeCommonEvent(0, 90015005, 30001510, 30002810, 30000810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 30000810, 940000, 30000810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 30000810, 940000, 30000810, 0, 0);
S5:
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 30000810, 8160);
    }
    $InitializeEvent(0, 30002930, 30005210, 30002200);
    $InitializeEvent(1, 30002930, 30005211, 30002201);
    $InitializeCommonEvent(0, 90035280, 30002491, 30000700, 30000701, 30000702, 8060, 0, 30000800, 30000810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 30002491, 30000700, 30000701, 30000702, 80010, 0, 30000800, 30000810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 30002491, 30000700, 30000701, 30000702, 80011, 1, 30000800, 30000810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035281, 30002491, 30000700, 30000701, 30000702, 80011, 30000800, 30000810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035282, 30000490, 30002490, 30000700, 30000701, 30000702, 30000703);
    $InitializeCommonEvent(0, 90035283, 30000490, 30002491, 30001690, 30000700, 30000701, 30000702, 30000704, 30000705, 30000706);
    $InitializeCommonEvent(0, 90035284, 30005490, 30005491, 30000700, 30000702, 30000705, 30000706);
    $InitializeCommonEvent(0, 90035285, 30000490, 30000700, 30000701, 30000702, 30000705, 30000706);
    $InitializeCommonEvent(0, 90035286, 30000490, 30002491, 30000700, 30000701, 30000702, 30000705, 30000706);
    $InitializeCommonEvent(0, 90035288, 30002491, 30000700, 30000702, 30000705, 30000706);
    $InitializeCommonEvent(0, 90015000, 30000704, 30000490, 907640001, 50, 0, 30000706);
    $InitializeCommonEvent(0, 99055500, 30000490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 30000704, 30000705, 30000490, 1020, 0, -1, -1, 30000490, 0);
    $InitializeCommonEvent(0, 90015009, 30008000, 30001600, 0, 0);
    $InitializeCommonEvent(1, 90015009, 30008000, 30001600, 1, 0);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 30000800);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 30000810);
});

$Event(30002900, Restart, function() {
    WaitFor(!InsidePlayArea(30000239, 0));
    ClearCharactersAITarget(30000239);
    RequestCharacterAIReplan(30000239);
    WaitFixedTimeFrames(1);
    DisableCharacterAI(30000239);
    WaitFor(InsidePlayArea(30000239, 0));
    EnableCharacterAI(30000239);
    RestartEvent();
});

$Event(30002920, Restart, function(eventFlagId, chrEntityId, assetEntityId, distance) {
    if (!EventFlag(eventFlagId)) {
        DisableCharacter(chrEntityId);
        DisableAsset(assetEntityId);
        WaitFixedTimeSeconds(1);
        WaitFor(EventFlag(eventFlagId));
        SpawnOneshotSFX(TargetEntityType.Asset, assetEntityId, 200, 1060);
        RecordUserDispLog(10106, 20000, LogObjectType.None, -1);
        WaitFixedTimeSeconds(0.5);
        EnableCharacter(chrEntityId);
        EnableAsset(assetEntityId);
    }
L0:
    RegisterBonfire(assetEntityId, 0, distance);
});

$Event(30002930, Restart, function(chrEntityId, areaEntityId) {
    WaitFor(ElapsedSeconds(1));
    SetSpEffect(chrEntityId, 8081);
    WaitFor(InArea(20000, areaEntityId));
    ClearSpEffect(chrEntityId, 8081);
    WaitFor(!InArea(20000, areaEntityId));
    RestartEvent();
});
