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
        if (EventFlag(48700000)) {
            $InitializeCommonEvent(0, 90055000, 48705200, 1, 48702200, 48700201);
            $InitializeCommonEvent(0, 90055001, 48705200, 1, 48700201, 48700200);
        }
        if (EventFlag(48700001)) {
            $InitializeCommonEvent(0, 90055000, 48705200, 2, 48702200, 48700201);
            $InitializeCommonEvent(0, 90055001, 48705200, 2, 48700201, 48700200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 48700200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 48702200, 48700200);
        $InitializeCommonEvent(0, 99055400, 48702200, 48700200);
        $InitializeCommonEvent(0, 99055300, 48702200, 48700200);
        $InitializeCommonEvent(0, 99055200, 48700200, 48700800, 48700810);
    }
    $InitializeCommonEvent(0, 90035001, 48700800);
    $InitializeCommonEvent(0, 90065910, 48700200, 48700205, 48700800, 356000, 690047, 48705210, 48700800, 903560000, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 48700200, 48700800, 356000, 48705210, 48700800, 903560000, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 48700800, 2, 0, 0, 1050, 356000, 903560000, 48700800);
    }
    $InitializeCommonEvent(0, 90015012, 48705210, 48700200);
    $InitializeCommonEvent(1, 90015012, 0, 48700200);
    $InitializeCommonEvent(0, 90015020, 48700200, 48700800);
    $InitializeCommonEvent(0, 90015008, 48700205, 48700800, 356000, 48700800, 15451, 0);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 48702200, 48700800);
        $InitializeCommonEvent(0, 90015023, 48700200, 40, 0, 48705210, 48700800, 903560000, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 48700200, 48705210, 40, 356000, 0);
        $InitializeCommonEvent(0, 90015002, 0, 48700200, 48700800, 48705210, 1010, 356000, 110320, 903560000, 48700800);
        $InitializeCommonEvent(0, 90015470, 48702200, 48700200, 48700800, 48705210, 0, 0, 48705210);
        $InitializeCommonEvent(0, 90015446, 48705210, 48700200, 48700800, 48702200);
        $InitializeCommonEvent(0, 90015460, 48702200, 48700800);
        $InitializeCommonEvent(0, 90015460, 48702200, 0);
        $InitializeCommonEvent(0, 90015460, 48702200, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 48702200, 48700800);
        $InitializeCommonEvent(0, 90015475, 48702200, 0);
        $InitializeCommonEvent(0, 90015475, 48702200, 0);
    }
    if (1 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48700000, 48700300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48700000, 48700300);
    }
    if (1 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48700000, 48700300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48700000, 48700300);
    }
    if (1 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48700000, 48700300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48700000, 48700300);
    }
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 48700000, 48700301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 48700000, 48700301);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 48700000, 48700301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 48700000, 48700301);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 48700000, 48700301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 48700000, 48700301);
    }
});

$Event(48702800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3) {
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

$Event(48702810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5) {
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
    ForceAnimationPlayback(48700800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(48700801);
    EnableCharacterAI(chrEntityId);
    SetNetworkUpdateRate(48700800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
});
