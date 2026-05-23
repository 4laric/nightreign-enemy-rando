// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015310, 32000050, 32000051, 2, 32000200, 32000202, 32000203, 32002405, 32002406, 32002407, 32002410, 32002411, 32002412, 32002415, 32002416, 32002417, 32002420, 32002421, 32002422, 32002400);
    $InitializeCommonEvent(0, 90015301, 32005300, 32000200, 32000201, 32000202, 32000203, 2);
    $InitializeCommonEvent(0, 90015306, 32006500);
    $InitializeCommonEvent(0, 90015303, 32002401);
    $InitializeCommonEvent(0, 90015305, 32002430, 32002431, 32002432, 32002433);
    $InitializeCommonEvent(0, 90015304, 32000050, 32000200, 32000202);
    if (2 >= 2) {
        $InitializeCommonEvent(0, 90015304, 32000051, 32000200, 32000203);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 32005800, 32002800, 30, 903010001, 0, 0);
        $InitializeCommonEvent(0, 99055500, 32005800, 15);
        $InitializeCommonEvent(0, 90015031, 0, 32005800, 32002800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 32005800, 32002800, 30, 903010001, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 32005800, 32002800, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 32000800, 32005800, 1030, 940000, 11200, 903010001, 32000500);
    $InitializeCommonEvent(0, 90015006, 32001500, 32000500, 32000800, 5);
    $InitializeCommonEvent(0, 90015005, 32001500, 32002800, 32000800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 32000800, 940000, 32005800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 32000800, 940000, 32005800, 0, 0);
S2:
    if (IsMapVariation(0)) {
        $InitializeCommonEvent(0, 90015050, 32000800, 8165);
    }
    if (940000 == 0) {
        $InitializeCommonEvent(0, 90015007, 0, 32000810, 32002810, 30, 904270600, 0, 0);
        $InitializeCommonEvent(0, 99055500, 32000810, 15);
        $InitializeCommonEvent(0, 90015031, 0, 32000810, 32002810, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015007, 0, 32000810, 32002810, 30, 904270600, 0, 0);
        $InitializeCommonEvent(0, 90015031, 0, 32000810, 32002810, 30, 940000, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 32000810, 32000810, 1030, 940000, 11200, 904270600, 32000810);
    $InitializeCommonEvent(0, 90015006, 32001510, 32000510, 32000810, 5);
    $InitializeCommonEvent(0, 90015005, 32001510, 32002810, 32000810);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 940000 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 32000810, 940000, 32000810, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 32000810, 940000, 32000810, 0, 0);
S5:
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90015050, 32000810, 8165);
    }
    $InitializeCommonEvent(0, 90035280, 32002491, 32000700, 32000701, 32000702, 8060, 0, 32000800, 32000810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 32002491, 32000700, 32000701, 32000702, 80010, 0, 32000800, 32000810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035280, 32002491, 32000700, 32000701, 32000702, 80011, 1, 32000800, 32000810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035281, 32002491, 32000700, 32000701, 32000702, 80011, 32000800, 32000810, 0, 0, 0);
    $InitializeCommonEvent(0, 90035282, 32000490, 32002490, 32000700, 32000701, 32000702, 32000703);
    $InitializeCommonEvent(0, 90035283, 32000490, 32002491, 32001690, 32000700, 32000701, 32000702, 32000704, 32000705, 32000706);
    $InitializeCommonEvent(0, 90035284, 32005490, 32005491, 32000700, 32000702, 32000705, 32000706);
    $InitializeCommonEvent(0, 90035285, 32000490, 32000700, 32000701, 32000702, 32000705, 32000706);
    $InitializeCommonEvent(0, 90035286, 32000490, 32002491, 32000700, 32000701, 32000702, 32000705, 32000706);
    $InitializeCommonEvent(0, 90035288, 32002491, 32000700, 32000702, 32000705, 32000706);
    $InitializeCommonEvent(0, 90015000, 32000704, 32000490, 907640001, 50, 0, 32000706);
    $InitializeCommonEvent(0, 99055500, 32000490, 15);
    $InitializeCommonEvent(0, 90015025, 8081, 32000704, 32000705, 32000490, 1020, 0, -1, -1, 32000490, 0);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 0, 32000800);
    $InitializeCommonEvent(0, 90085700, 701, 8475, 1, 32000810);
});

$Event(32002900, Default, function(eventFlagId, chrEntityId, nameId) {
    DisableNetworkSync();
    if (eventFlagId != 0) {
        WaitFor(EventFlag(eventFlagId));
    }
    WaitFor(
        (CharacterAIState(32000351, AIStateType.Normal, NotEqual, 1)
            || CharacterAIState(32000352, AIStateType.Normal, NotEqual, 1))
            && InArea(20000, 32002490));
    flag = !EventFlag(5000);
    flag2 = !EventFlag(5001);
    flag3 = flag || flag2;
    if (!flag3) {
        WaitFor(flag3);
        RestartEvent();
    }
    WaitFixedTimeSeconds(1);
    if (flag.Passed) {
        SetEventFlagID(5000, ON);
        DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
    } else if (flag2.Passed) {
        SetEventFlagID(5001, ON);
        DisplayBossHealthBar(Enabled, chrEntityId, 1, nameId);
    }
    area = !InArea(20000, 32002490);
    chr = CharacterRatioDead(32005202);
    WaitFor(area || chr);
    if (!chr.Passed) {
        WaitFixedTimeSeconds(3);
    } else {
        WaitFixedTimeSeconds(1);
    }
    if (flag.Passed) {
        SetEventFlagID(5000, OFF);
        DisplayBossHealthBar(Disabled, chrEntityId, 0, nameId);
    } else if (flag2.Passed) {
        SetEventFlagID(5001, OFF);
        DisplayBossHealthBar(Disabled, chrEntityId, 1, nameId);
    }
    EndIf(chr.Passed);
    RestartEvent();
});

$Event(32002910, Restart, function(eventFlagId, chrEntityId, assetEntityId, distance) {
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
