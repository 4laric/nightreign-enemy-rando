// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeEvent(0, 1056302529);
    if (0 == 0) {
        $InitializeCommonEvent(0, 90015021, 0, 1056300800, 904311000, 30, 0, 0, 74961);
        $InitializeCommonEvent(0, 99055500, 1056300800, 15);
        $InitializeCommonEvent(0, 90015030, 0, 1056300800, 30, 940000, 0);
    } else {
        $InitializeCommonEvent(0, 90015021, 0, 1056300800, 904311000, 30, 0, 0, 74961);
        $InitializeCommonEvent(0, 90015030, 0, 1056300800, 30, 0, 0);
    }
    $InitializeCommonEvent(0, 90015002, 0, 0, 1056300800, 1056300800, 1030, 0, 11200, 904311000, 1056300800);
    $InitializeCommonEvent(0, 90015006, 1056301500, 1056300500, 1056300800, 5);
    $InitializeCommonEvent(0, 90015005, 1056301500, 1056302800, 1056300800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S2);
S0:
    GotoIf(S1, 0 != 0);
    $InitializeCommonEvent(0, 90015008, 0, 1056300800, 940000, 1056300800, 0, 0);
    Goto(S2);
S1:
    $InitializeCommonEvent(0, 90015008, 0, 1056300800, 0, 1056300800, 0, 0);
S2:
    $InitializeCommonEvent(0, 90005904, 0, 1056301290, 100, 6101);
    $InitializeCommonEvent(0, 90015150, 1056300291, 73093);
    $InitializeCommonEvent(0, 90015151, 1056300291, 74053);
    $InitializeCommonEvent(0, 90015152, 1056300291, 74053);
});

$Event(1056302510, Restart, function(assetEntityId, eventFlagId, objactEventFlag, objactParamId, distance) {
    if (!EventFlag(eventFlagId)) {
        WaitFor(ObjActEventFlag(objactEventFlag));
        SetNetworkconnectedEventFlagID(eventFlagId, ON);
        RecordUserDispLog(10100, assetEntityId, LogObjectType.None, -1);
    }
L0:
    Unknown200391(assetEntityId, distance);
    DisableObjAct(assetEntityId, objactParamId);
    EndEvent();
});

$Event(1056302529, Restart, function() {
    DisableNetworkSync();
    WaitFor(EventFlag(7603) && InArea(20000, 1056302529));
    SetSpEffect(20000, 99130);
    WaitFixedTimeSeconds(1);
    RestartEvent();
});

$Event(1056302530, Restart, function(eventFlagId, assetEntityId) {
    DisableNetworkSync();
    if (EventFlag(eventFlagId)) {
        DisableAsset(assetEntityId);
        EndEvent();
    }
    WaitFor(ActionButtonInArea(9030, assetEntityId));
    SetSpEffect(20000, 8971310);
    DisableAsset(assetEntityId);
    SetEventFlagID(eventFlagId, ON);
});

$Event(1056302700, Restart, function(entityId) {
    CreateBulletOwner(1056300600);
    DisableNetworkSync();
    WaitFor(ActionButtonInArea(7810, entityId));
    SpawnOneshotSFX(TargetEntityType.Asset, entityId, 90, 803200);
    ShootBullet(1056300600, entityId, -1, 180070, 0, 0, 0);
    WaitFor(ElapsedSeconds(30));
    RestartEvent();
});

$Event(200, Default, function() {
    $InitializeCommonEvent(0, 90005917, 1056301510, 1056304580, 90040, 300);
});
