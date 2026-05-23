// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1048200371, 15);
    RegisterBonfire(1048201960, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1048201960, 1048200960);
    RegisterBonfire(1048201950, 0, 5);
    $InitializeCommonEvent(0, 90015004, 1048201950, 1048200950);
    $InitializeCommonEvent(0, 90005200, 1048200200, 30003, 20003, 1048202200, 0.1, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1048200201, 30003, 20003, 1048202200, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1048200202, 30003, 20003, 1048202200, 0.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1048200203, 30003, 20003, 1048202200, 0.9, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1048200204, 30003, 20003, 1048202200, 1.5, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1048200205, 30003, 20003, 1048202200, 1.2, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005200, 1048200206, 30003, 20003, 1048202200, 0.3, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005250, 1048200300, 1048202300, 0, -1);
    $InitializeCommonEvent(0, 90005200, 1048200304, 30003, 20003, 1048202301, 0, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90005260, 1048200371, 1049202370, 35, 0, -1);
    $InitializeCommonEvent(0, 90015150, 1048200290, 73087);
    $InitializeCommonEvent(0, 90015151, 1048200290, 74047);
    $InitializeCommonEvent(0, 90015152, 1048200290, 74047);
    $InitializeCommonEvent(0, 90005200, 1048200800, 30001, 20001, 1048202800, 0, 0, 0, 0, 0);
    if (920910 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 1048200800, 904910320, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 1048200800, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1048200800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 1048200800, 904910320, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 1048200800, 30, 920910, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1048202800, 1048200800, 1020, 920910, 11200, 904910320, 1048200800);
    $InitializeCommonEvent(0, 90015006, 1048201500, 1048200500, 1048202800, 5);
    $InitializeCommonEvent(0, 90015005, 1048201500, 1048202800, 1048202800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 920910 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1048202800, 940000, 1048200800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 1048202800, 920910, 1048200800, 0, 0);
S2:
    $InitializeCommonEvent(0, 90015017, 1048200800, 0, 1048202800, 1048202800, 72446, 1048202800);
    $InitializeCommonEvent(0, 90015041, 230, 0, 0, 72477);
    if (920810 == 0) {
        $InitializeCommonEvent(0, 90015000, 0, 1048200830, 904680320, 30, 0, 0);
        $InitializeCommonEvent(0, 99055500, 1048200830, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1048200830, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015000, 0, 1048200830, 904680320, 30, 0, 0);
        $InitializeCommonEvent(0, 90015030, 0, 1048200830, 30, 920810, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1048202830, 1048200830, 1020, 920810, 11200, 904680320, 1048200830);
    $InitializeCommonEvent(0, 90015006, 1048201530, 1048200530, 1048202830, 5);
    $InitializeCommonEvent(0, 90015005, 1048201530, 1048202830, 1048202830);
    GotoIf(S3, Signed(0) != 0);
    GotoIf(S3, 0 != 0);
    Goto(S5);
S3:
    GotoIf(S4, 920810 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1048202830, 940000, 1048200830, 0, 0);
    Goto(S5);
S4:
    $InitializeCommonEvent(0, 90015008, 0, 1048202830, 920810, 1048200830, 0, 0);
S5:
    $InitializeCommonEvent(0, 90015017, 1048200830, 25, 0, 1048202830, 72447, 1048202830);
    $InitializeCommonEvent(0, 90015041, 0, 0, 0, 72478);
    $InitializeEvent(0, 1048202500, 1048200400, 400, 1048202400, 10109, 1048202800, 9194);
    $InitializeEvent(0, 1048202501, 1048201300, 807038, 100, 1048202800, 9194, 1048200800);
    $InitializeCommonEvent(0, 91005503, 1048201550);
    $InitializeEvent(0, 1048202220, 1048202350, 1048204350);
});

$Event(1048202500, Default, function(chrEntityId, operationGuideParamId, entityId, userDispLogParamId, eventFlagId, eventFlagId2) {
    DisableNetworkSync();
    if (EventFlag(eventFlagId2)) {
        EnableCharacter(chrEntityId);
        HideFloatingMessage(operationGuideParamId, entityId);
        EndEvent();
    }
L0:
    if (!EventFlag(eventFlagId)) {
        DisableCharacter(chrEntityId);
        ShowFloatingMessage(operationGuideParamId, entityId);
        WaitFor(EventFlag(eventFlagId));
        RecordUserDispLog(userDispLogParamId, chrEntityId, LogObjectType.None, -1);
    }
L1:
    EnableCharacter(chrEntityId);
    HideFloatingMessage(operationGuideParamId, entityId);
    WaitFor(EventFlag(eventFlagId2));
    WaitFixedTimeSeconds(0.5);
    DisplayTextEffectId(2210);
});

$Event(1048202501, Default, function(assetEntityId, sfxId, dummypolyId, eventFlagId, eventFlagId2, chrEntityId) {
    DisableNetworkSync();
    if (EventFlag(eventFlagId2)) {
        DeleteAssetfollowingSFX(assetEntityId, false);
        EndEvent();
    }
L0:
    if (!EventFlag(eventFlagId)) {
        if (!SpecialStandbyEndedFlag(chrEntityId)) {
            CreateAssetfollowingSFX(assetEntityId, dummypolyId, sfxId);
            WaitFor(SpecialStandbyEndedFlag(chrEntityId) || EventFlag(eventFlagId));
            GotoIf(L3, EventFlag(eventFlagId));
        }
L2:
        DeleteAssetfollowingSFX(assetEntityId, true);
        WaitFor(EventFlag(eventFlagId));
    }
L1:
    CreateAssetfollowingSFX(assetEntityId, dummypolyId, sfxId);
L3:
    WaitFor(EventFlag(eventFlagId2));
    DeleteAssetfollowingSFX(assetEntityId, true);
});

$Event(1048202220, Restart, function(areaEntityId, eventFlagId) {
    DisableNetworkSync();
    if (!EventFlag(eventFlagId)) {
        WaitFor(InArea(20000, areaEntityId));
        SetEventFlagID(eventFlagId, ON);
        WaitFixedTimeSeconds(0.1);
    }
L0:
    WaitFor(!InArea(20000, areaEntityId) && !InArea(20000, 1048202360));
    SetEventFlagID(eventFlagId, OFF);
    WaitFixedTimeSeconds(0.1);
    RestartEvent();
});
