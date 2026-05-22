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
        if (EventFlag(49250000)) {
            $InitializeCommonEvent(0, 90055000, 49255200, 1, 49252200, 49250201);
            $InitializeCommonEvent(0, 90055001, 49255200, 1, 49250201, 49250200);
        }
        if (EventFlag(49250001)) {
            $InitializeCommonEvent(0, 90055000, 49255200, 2, 49252200, 49250201);
            $InitializeCommonEvent(0, 90055001, 49255200, 2, 49250201, 49250200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49250200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49252200, 49250200);
        $InitializeCommonEvent(0, 99055400, 49252200, 49250200);
        $InitializeCommonEvent(0, 99055300, 49252200, 49250200);
        $InitializeCommonEvent(0, 99055200, 49250200, 49250800, 49250810);
    }
    $InitializeCommonEvent(0, 90065121, 49250200, 49250205, 49250800, 920200, 690047, 49255210, 49250800, 902500300, 49250810, 905011000, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49250200, 49250800, 920200, 49255210, 49250800, 902500300, 49250810, 905011000, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49250800, 2, 0, 0, 1050, 920200, 902500300, 49250800);
    }
    $InitializeCommonEvent(0, 90015012, 49255210, 49250200);
    $InitializeCommonEvent(1, 90015012, 0, 49250200);
    $InitializeCommonEvent(0, 90015020, 49250200, 49250800);
    $InitializeCommonEvent(0, 90015008, 49250205, 49250800, 920200, 49255210, 14601, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065120, 49250800, 49250810, 49250200, 49250800, 905011000, 49250206);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065122, 49250800, 49250810, 49250200, 49250800, 905011000, 49250206, 49250207);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49252200, 49250800);
        $InitializeCommonEvent(0, 90015023, 49250200, 40, 0, 49255210, 49250800, 902500300, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015026, 49250206, 40, 0, 49255210, 49250810, 905011000);
        $InitializeCommonEvent(0, 90015030, 49250200, 49255210, 40, 920200, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49250200, 49250800, 49255210, 1020, 920200, 110320, 902500300, 49250800);
        $InitializeCommonEvent(0, 90015470, 49252200, 49250200, 49250800, 49255210, 0, 0, 49255210);
        $InitializeCommonEvent(0, 90015478, 49250800, 49250800);
        $InitializeCommonEvent(0, 90015478, 49250810, 49250800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 49255210, 49250200, 49250800, 49252200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 49252200, 49250800);
        $InitializeCommonEvent(0, 90015460, 49252200, 49250810);
        $InitializeCommonEvent(0, 90015460, 49252200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49252200, 49250800);
        $InitializeCommonEvent(0, 90015475, 49252200, 49250810);
        $InitializeCommonEvent(0, 90015475, 49252200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 49250800);
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49250000, 49250300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49250000, 49250300);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49250000, 49250300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49250000, 49250300);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49250000, 49250300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49250000, 49250300);
    }
    if (3 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49250000, 49250301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49250000, 49250301);
    }
    if (3 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49250000, 49250301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49250000, 49250301);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49250000, 49250301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49250000, 49250301);
    }
});

$Event(49252800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3, chrEntityId3) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFor(HPRatio(chrEntityId3) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 902500520);
    DisplayBossHealthBar(Disabled, chrEntityId3, 1, 902500520);
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
    DisableCharacter(chrEntityId3);
});

$Event(49252810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5, chrEntityId2) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacter(chrEntityId2);
        DisableCharacterCollision(chrEntityId);
        DisableCharacterCollision(chrEntityId2);
        ForceCharacterDeath(chrEntityId, false);
        ForceCharacterDeath(chrEntityId2, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacter(chrEntityId2);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterCollision(chrEntityId2);
    DisableCharacterAI(chrEntityId);
    DisableCharacterAI(chrEntityId2);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));
    WaitFixedTimeSeconds(1);
    EnableCharacter(chrEntityId);
    EnableCharacter(chrEntityId2);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterCollision(chrEntityId2);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(chrEntityId2);
    ForceAnimationPlayback(48600800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(chrEntityId2);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(chrEntityId2);
    SetNetworkUpdateRate(48600800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
    DisplayBossHealthBar(Enabled, chrEntityId2, 0, nameId);
});
