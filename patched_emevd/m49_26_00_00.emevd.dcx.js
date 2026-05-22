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
        if (EventFlag(49260000)) {
            $InitializeCommonEvent(0, 90055000, 49265200, 1, 49262200, 49260201);
            $InitializeCommonEvent(0, 90055001, 49265200, 1, 49260201, 49260200);
        }
        if (EventFlag(49260001)) {
            $InitializeCommonEvent(0, 90055000, 49265200, 2, 49262200, 49260201);
            $InitializeCommonEvent(0, 90055001, 49265200, 2, 49260201, 49260200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49260200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49262200, 49260200);
        $InitializeCommonEvent(0, 99055400, 49262200, 49260200);
        $InitializeCommonEvent(0, 99055300, 49262200, 49260200);
        $InitializeCommonEvent(0, 99055200, 49260200, 49260800, 49260810);
    }
    $InitializeCommonEvent(0, 90065910, 49260200, 49260205, 49260800, 950000, 690046, 49260800, 49260800, 903050500, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49260200, 49260800, 950000, 49260800, 49260800, 903050500, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49260800, 2, 0, 0, 1050, 950000, 903050500, 49260800);
    }
    $InitializeCommonEvent(0, 90015012, 49260800, 49260200);
    $InitializeCommonEvent(1, 90015012, 49265801, 49260200);
    $InitializeCommonEvent(0, 90015020, 49260200, 49260800);
    $InitializeCommonEvent(0, 90015008, 49260205, 49260800, 950000, 49260800, 11100, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065061, 49260800, 49260810, 20015, 53, 11130, 49260210, 49260200, 49260800);
        $InitializeCommonEvent(0, 90065061, 49260800, 49260811, 20015, 55, 11130, 49260210, 49260200, 49260800);
    }
    $InitializeCommonEvent(0, 90065060, 49260800, 49260205, 49260210, 49260800);
    $InitializeCommonEvent(0, 90065062, 49260800, 49265801, 49260200, 49260800);
    $InitializeCommonEvent(0, 90065063, 49260800, 49265801, 49260200, 49260800);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49262200, 49260800);
        $InitializeCommonEvent(0, 90015023, 49260200, 40, 0, 49260800, 49260800, 903050500, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49260200, 49260800, 40, 950000, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49260200, 49260800, 49260800, 1020, 950000, 110320, 903050500, 49260800);
        $InitializeCommonEvent(0, 90015470, 49262200, 49260200, 49260800, 49260800, 49265801, 0, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065064, 49260800, 49260810, 20015, 53, 11130, 0, 0, 49260210, 49260200, 49260800);
        $InitializeCommonEvent(0, 90065064, 49260800, 49260811, 20015, 55, 11130, 0, 0, 49260210, 49260200, 49260800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 49260800, 49260200, 49260800, 49262200);
        $InitializeCommonEvent(0, 90015446, 49265801, 49260200, 49260800, 49262200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 49262200, 49260800);
        $InitializeCommonEvent(0, 90015460, 49262200, 49260810);
        $InitializeCommonEvent(0, 90015460, 49262200, 49260811);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49262200, 49260800);
        $InitializeCommonEvent(0, 90015475, 49262200, 49260810);
        $InitializeCommonEvent(0, 90015475, 49262200, 49260811);
    }
    $InitializeCommonEvent(0, 90035001, 49265800);
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49260000, 49260300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49260000, 49260300);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49260000, 49260300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49260000, 49260300);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49260000, 49260300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49260000, 49260300);
    }
    if (3 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49260000, 49260301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49260000, 49260301);
    }
    if (3 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49260000, 49260301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49260000, 49260301);
    }
    if (3 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49260000, 49260301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49260000, 49260301);
    }
});

$Event(49262800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3, chrEntityId3, chrEntityId4) {
    EndIf(EventFlag(eventFlagId));
    EndIf(EventFlag(eventFlagId2));
    WaitFor(HPRatio(chrEntityId) <= 0);
    WaitFor(HPRatio(chrEntityId3) <= 0);
    WaitFor(HPRatio(chrEntityId4) <= 0);
    WaitFixedTimeSeconds(4);
    WaitFor(CharacterDead(chrEntityId));
    DisplayBossHealthBar(Disabled, chrEntityId, 0, 903050700);
    DisplayBossHealthBar(Disabled, chrEntityId3, 1, 903010000);
    DisplayBossHealthBar(Disabled, chrEntityId4, 2, 903010000);
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
    DisableCharacter(chrEntityId4);
});

$Event(49262810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5, chrEntityId2, chrEntityId3) {
    if (EventFlag(eventFlagId4) || EventFlag(eventFlagId5)) {
        DisableCharacter(chrEntityId);
        DisableCharacter(chrEntityId2);
        DisableCharacter(chrEntityId3);
        DisableCharacterCollision(chrEntityId);
        DisableCharacterCollision(chrEntityId2);
        DisableCharacterCollision(chrEntityId3);
        ForceCharacterDeath(chrEntityId, false);
        ForceCharacterDeath(chrEntityId2, false);
        ForceCharacterDeath(chrEntityId3, false);
        EndEvent();
    }
L0:
    DisableCharacter(chrEntityId);
    DisableCharacter(chrEntityId2);
    DisableCharacter(chrEntityId3);
    DisableCharacterCollision(chrEntityId);
    DisableCharacterCollision(chrEntityId2);
    DisableCharacterCollision(chrEntityId3);
    DisableCharacterAI(chrEntityId);
    DisableCharacterAI(chrEntityId2);
    DisableCharacterAI(chrEntityId3);
    flag = EventFlag(7515) && (EventFlag(eventFlagId) || EventFlag(eventFlagId2));
    WaitFor((EventFlag(eventFlagId3)) || ElapsedSeconds(90));
    WaitFixedTimeSeconds(1);
    EnableCharacter(chrEntityId);
    EnableCharacter(chrEntityId2);
    EnableCharacter(chrEntityId3);
    EnableCharacterCollision(chrEntityId);
    EnableCharacterCollision(chrEntityId2);
    EnableCharacterCollision(chrEntityId3);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(chrEntityId2);
    EnableCharacterAI(chrEntityId3);
    ForceAnimationPlayback(48600800, 20005, false, false, false);
    DisableCharacterHPBarDisplay(chrEntityId);
    DisableCharacterHPBarDisplay(chrEntityId2);
    DisableCharacterHPBarDisplay(chrEntityId3);
    EnableCharacterAI(chrEntityId);
    EnableCharacterAI(chrEntityId2);
    EnableCharacterAI(chrEntityId3);
    SetNetworkUpdateRate(48600800, true, CharacterUpdateFrequency.AlwaysUpdate);
    DisplayBossHealthBar(Enabled, chrEntityId, 0, nameId);
    DisplayBossHealthBar(Enabled, chrEntityId2, 0, 903010000);
    DisplayBossHealthBar(Enabled, chrEntityId3, 0, 903010000);
});
