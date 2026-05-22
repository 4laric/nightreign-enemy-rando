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
        if (EventFlag(49270000)) {
            $InitializeCommonEvent(0, 90055000, 49275200, 1, 49272200, 49270201);
            $InitializeCommonEvent(0, 90055001, 49275200, 1, 49270201, 49270200);
        }
        if (EventFlag(49270001)) {
            $InitializeCommonEvent(0, 90055000, 49275200, 2, 49272200, 49270201);
            $InitializeCommonEvent(0, 90055001, 49275200, 2, 49270201, 49270200);
        }
    }
    if (IsMapVariation(1)) {
        $InitializeCommonEvent(0, 90035000, 49270200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015442, 49272200, 49270200);
        $InitializeCommonEvent(0, 99055400, 49272200, 49270200);
        $InitializeCommonEvent(0, 99055300, 49272200, 49270200);
        $InitializeCommonEvent(0, 99055200, 49270200, 49270800, 49270810);
    }
    $InitializeCommonEvent(0, 90065910, 49270200, 49270205, 49270800, 950000, 690046, 49270800, 49270800, 903050600, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90065911, 49270200, 49270800, 950000, 49270800, 49270800, 903050600, 0, 0, 0, 0, 0);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065900, 49270800, 1, 0, 0, 1050, 950000, 903050600, 49270800);
    }
    $InitializeCommonEvent(0, 90015008, 49270205, 49270800, 950000, 49270800, 0, 0.55);
    $InitializeCommonEvent(0, 90015012, 49270800, 49270200);
    $InitializeCommonEvent(1, 90015012, 49275801, 49270200);
    $InitializeCommonEvent(0, 90015020, 49270200, 49270800);
    if (!IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065061, 49270800, 49270810, 20015, 179, 11130, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065061, 49270800, 49270811, 20015, 52, 11130, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065061, 49270800, 49270812, 20015, 53, 11130, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065061, 49270800, 49270813, 20015, 54, 11130, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065061, 49270800, 49270814, 20015, 55, 11130, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065061, 49270800, 49270820, 20015, 179, 11131, 49270211, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065061, 49270800, 49270821, 20015, 52, 11131, 49270211, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065061, 49270800, 49270822, 20015, 54, 11131, 49270211, 49270200, 49270800);
    }
    $InitializeCommonEvent(0, 90065062, 49270800, 49275801, 49270200, 49270800);
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015443, 49272200, 49270800);
        $InitializeCommonEvent(0, 90015023, 49270200, 40, 0, 49270800, 49270800, 903050600, 0, 0, 0, 0);
        $InitializeCommonEvent(0, 90015030, 49270200, 49270800, 40, 950000, 0);
        $InitializeCommonEvent(0, 90015002, 0, 49270200, 49270800, 49270800, 1020, 950000, 110320, 903050600, 49270800);
        $InitializeCommonEvent(0, 90015470, 49272200, 49270200, 49270800, 49270800, 49275801, 0, 0);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90065064, 49270800, 49270810, 20015, 179, 11130, 49272290, 49272291, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065064, 49270800, 49270811, 20015, 52, 11130, 49272290, 49272292, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065064, 49270800, 49270812, 20015, 53, 11130, 49272290, 49272293, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065064, 49270800, 49270813, 20015, 54, 11130, 49272290, 49272294, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065064, 49270800, 49270814, 20015, 55, 11130, 49272290, 49272295, 49270210, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065064, 49270800, 49270820, 20015, 179, 11131, 49272290, 49272293, 49270211, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065064, 49270800, 49270821, 20015, 52, 11131, 49272290, 49272294, 49270211, 49270200, 49270800);
        $InitializeCommonEvent(0, 90065064, 49270800, 49270822, 20015, 53, 11131, 49272290, 49272295, 49270211, 49270200, 49270800);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015446, 49270800, 49270200, 49270800, 49272200);
        $InitializeCommonEvent(0, 90015446, 49275801, 49270200, 49270800, 49272200);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015460, 49272200, 49270800);
        $InitializeCommonEvent(0, 90015460, 49272200, 49270810);
        $InitializeCommonEvent(0, 90015460, 49272200, 49270811);
        $InitializeCommonEvent(0, 90015460, 49272200, 49270812);
        $InitializeCommonEvent(0, 90015460, 49272200, 49270813);
        $InitializeCommonEvent(0, 90015460, 49272200, 49270814);
        $InitializeCommonEvent(0, 90015460, 49272200, 49270820);
        $InitializeCommonEvent(0, 90015460, 49272200, 49270821);
        $InitializeCommonEvent(0, 90015460, 49272200, 49270822);
    }
    if (IsMapVariation(2)) {
        $InitializeCommonEvent(0, 90015475, 49272200, 49270800);
        $InitializeCommonEvent(0, 90015475, 49272200, 49270810);
        $InitializeCommonEvent(0, 90015475, 49272200, 49270811);
        $InitializeCommonEvent(0, 90015475, 49272200, 49270812);
        $InitializeCommonEvent(0, 90015475, 49272200, 49270813);
        $InitializeCommonEvent(0, 90015475, 49272200, 49270814);
        $InitializeCommonEvent(0, 90015475, 49272200, 49270820);
        $InitializeCommonEvent(0, 90015475, 49272200, 49270821);
        $InitializeCommonEvent(0, 90015475, 49272200, 49270822);
    }
    $InitializeCommonEvent(0, 90035001, 49275800);
    if (1 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49270000, 49270300);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49270000, 49270300);
    }
    if (1 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49270000, 49270300);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49270000, 49270300);
    }
    if (1 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49270000, 49270300);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49270000, 49270300);
    }
    if (2 == 1) {
        $InitializeCommonEvent(0, 90015070, 1056402601, 49270000, 49270301);
        $InitializeCommonEvent(0, 90015070, 1028402600, 49270000, 49270301);
    }
    if (2 == 2) {
        $InitializeCommonEvent(0, 90015070, 1056402602, 49270000, 49270301);
        $InitializeCommonEvent(0, 90015070, 1028402601, 49270000, 49270301);
    }
    if (2 == 3) {
        $InitializeCommonEvent(0, 90015070, 1056402603, 49270000, 49270301);
        $InitializeCommonEvent(0, 90015070, 1028402602, 49270000, 49270301);
    }
});

$Event(49272800, Default, function(chrEntityId, assetEntityId, chrEntityId2, eventFlagId, eventFlagId2, eventFlagId3, chrEntityId3, chrEntityId4) {
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

$Event(49272810, Restart, function(chrEntityId, eventFlagId, eventFlagId2, eventFlagId3, nameId, eventFlagId4, eventFlagId5, chrEntityId2, chrEntityId3) {
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
