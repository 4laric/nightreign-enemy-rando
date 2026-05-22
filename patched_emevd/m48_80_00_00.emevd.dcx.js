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
        if (EventFlag(48800000)) {
            $InitializeCommonEvent(0, 90055000, 48805200, 1, 48802200, 48800201);
            $InitializeCommonEvent(0, 90055001, 48805200, 1, 48800201, 48800200);
        }
        if (EventFlag(48800001)) {
            $InitializeCommonEvent(0, 90055000, 48805200, 2, 48802200, 48800201);
            $InitializeCommonEvent(0, 90055001, 48805200, 2, 48800201, 48800200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 48800200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 48802200, 48800200);
        $InitializeCommonEvent(0, 99055400, 48802200, 48800200);
        $InitializeCommonEvent(0, 99055300, 48802200, 48800200);
        $InitializeCommonEvent(0, 99055200, 48800200, 48800800, 48800810);
    }
    $InitializeCommonEvent(0, 90065131, 48800200, 48800205, 48800800, 356000, 690047, 48805210, 48800800, 903570000, 48800810, 903560000, 0, 0);
    $InitializeCommonEvent(0, 90065911, 48800200, 48800800, 356000, 48805210, 48800800, 903570000, 48800810, 903560000, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 48800800, 2, 0, 0, 1050, 356000, 903570000, 48800800);
    }
    $InitializeCommonEvent(0, 90015012, 48805210, 48800200);
    $InitializeCommonEvent(1, 90015012, 0, 48800200);
    $InitializeCommonEvent(0, 90015020, 48800200, 48800800);
    $InitializeCommonEvent(0, 90015008, 48800205, 48800800, 356000, 48805210, 15501, 0.5);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065130, 48800800, 48800810, 48800200, 48800800, 903560000, 48800206);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065132, 48800800, 48800810, 48800200, 48800800, 903560000, 48800206, 48800207);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 48802200, 48800800);
        $InitializeCommonEvent(0, 90015023, 48800200, 40, 0, 48805210, 48800800, 903570000, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015026, 48800206, 40, 0, 48805210, 48800810, 903560000);
        $InitializeCommonEvent(0, 90015030, 48800200, 48805210, 40, 356000, 0);
        $InitializeCommonEvent(0, 90015002, 0, 48800200, 48800800, 48805210, 1020, 356000, 110320, 903570000, 48800800);
        $InitializeCommonEvent(0, 90015470, 48802200, 48800200, 48800800, 48805210, 0, 0, 48805210);
        $InitializeCommonEvent(0, 90015478, 48800800, 48800800);
        $InitializeCommonEvent(0, 90015478, 48800810, 48800800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 48805210, 48800200, 48800800, 48802200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 48802200, 48800800);
        $InitializeCommonEvent(0, 90015460, 48802200, 48800810);
        $InitializeCommonEvent(0, 90015460, 48802200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 48802200, 48800800);
        $InitializeCommonEvent(0, 90015475, 48802200, 48800810);
        $InitializeCommonEvent(0, 90015475, 48802200, 0);
    }
    $InitializeCommonEvent(0, 90035001, 48800800);
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48800000, 48800300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48800000, 48800300);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48800000, 48800300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48800000, 48800300);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48800000, 48800300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48800000, 48800300);
    }
    if (3 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48800000, 48800301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48800000, 48800301);
    }
    if (3 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48800000, 48800301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48800000, 48800301);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48800000, 48800301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48800000, 48800301);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015476, 10002, 48802200);
        $InitializeCommonEvent(0, 90015476, 10003, 48802200);
        $InitializeCommonEvent(0, 90015476, 10004, 48802200);
    }
});

$Event(48802800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
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

$Event(48802810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
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
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(48800801);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(48800800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
