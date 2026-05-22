// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    DCX_KRAK
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    if (IsMapVariation(0)) {
        if (EventFlag(49240000)) {
            $InitializeCommonEvent(0, 90055000, 49245200, 1, 49242200, 49240201);
            $InitializeCommonEvent(0, 90055001, 49245200, 1, 49240201, 49240200);
        }
        if (EventFlag(49240001)) {
            $InitializeCommonEvent(0, 90055000, 49245200, 2, 49242200, 49240201);
            $InitializeCommonEvent(0, 90055001, 49245200, 2, 49240201, 49240200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49240200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49242200, 49240200);
        $InitializeCommonEvent(0, 99055400, 49242200, 49240200);
        $InitializeCommonEvent(0, 99055300, 49242200, 49240200);
        $InitializeCommonEvent(0, 99055200, 49240200, 49240800, 49240810);
    }
    $InitializeCommonEvent(0, 90065910, 49240200, 49240205, 49240800, 921000, 690046, 49245210, 49240800, 903100600, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49240200, 49240800, 921000, 49245210, 49240800, 903100600, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49240800, 1, 0, 0, 1050, 921000, 903100600, 49240800);
    }
    $InitializeCommonEvent(0, 90015012, 49245210, 49240200);
    $InitializeCommonEvent(1, 90015012, 0, 49240200);
    $InitializeCommonEvent(0, 90015020, 49240200, 49240800);
    $InitializeCommonEvent(0, 90015008, 49240205, 49240800, 921000, 49240800, 0, 0.55);
    $InitializeCommonEvent(0, 90065920, 49240800, 7300);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49242200, 49240800);
        $InitializeCommonEvent(0, 90015023, 49240200, 40, 0, 49245210, 49240800, 903100600, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49240200, 49245210, 40, 921000, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49240200, 49240800, 49245210, 1020, 921000, 110320, 903100600, 49240800);
        $InitializeCommonEvent(0, 90015470, 49242200, 49240200, 49240800, 49245210, 0, 0, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 49245210, 49240200, 49240800, 49242200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 49242200, 49240800);
        $InitializeCommonEvent(0, 90015460, 49242200, 0);
        $InitializeCommonEvent(0, 90015460, 49242200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49242200, 49240800);
        $InitializeCommonEvent(0, 90015475, 49242200, 0);
        $InitializeCommonEvent(0, 90015475, 49242200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 49240800);
});

$Event(49242800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 0);
    if (assetEntityId != 0) {
        EnableAsset(assetEntityId);
    }
    if (chrEntityId2 != 0) {
        EnableCharacter(chrEntityId2);
    }
    if (!EventFlag(eventFlagId3)) {
        SetEventFlagID(eventFlagId, ON);
        EndEvent();
    }
    SetEventFlagID(eventFlagId2, ON);
    WaitFor(ElapsedSeconds(3));
    DisableCharacter(chrEntityId);
});

$Event(49242810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacterCollision(chrEntityId);
        ForceCharacterDeath(chrEntityId, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterAI(chrEntityId);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));
    WaitFixedTimeSeconds(1);
    EnableCharacter(chrEntityId);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterAI(chrEntityId);
    ForceAnimationPlayback(48600800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(48600800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
