function [OrderlistR,newTraderecord] = fcb2016(optionhq,position,olist,option_last_frame)


pricematrix = optionhq';
rawHolding = position';
pricematrix00 = option_last_frame';
Olist = olist';
%see row45

interestRate = 0.03;
%daysToSettlement = 13; % - update everyday
desirMount = 1;
cap = 10;
Holdingcostmark = 5;       %100 for close out
Limitcost = 0;              %50000 for close out
Liquidcostmark = 0;             %40 for open
CurrentMonth = Olist(1,8);  %201602;
actionpoint = 12;           %15 for close out
limitordermark = 10;

OrderlistR = [0,0,0,0,0]'; %初始化 防止返回报错
newTraderecord = 0;

yymm = CurrentMonth;
%Olist=Olist(cellfun(@double,Olist(:,8))==yymm,:);          20160211
% Item = cell2mat(Olist(:,4));代码本来是在万德里头跑，调用它的合约列表，然后生成txt文件， feed到optlist里头的
% Item = str2num(Item(:,1:8))';代码本来是在万德里头跑，调用它的合约列表，然后生成txt文件， feed到optlist里头的
% dlmwrite('Olist.txt',Item,'precision',15);
% len = size(Olist,1);代码本来是在万德里头跑，调用它的合约列表，然后生成txt文件， feed到optlist里头的

% 
% 
% if  size(pricematrix,1) ~= size(olist,1)
%     Boxprofit = 0
%     break
% end


%cancate matrix;
Contract = (Olist(:,1));                            %20160211
%Contract = str2num(Contract1(:,1:8));              %20160211
Strike = (Olist(:,7));                              %20160211
SDate = Olist(:,8);                                 %20160211
%Prop = cell2mat(Olist(:,9)); 

% size=e(pricematrix,1) >= size(Olist,1)
Pricematrix = [Contract SDate Strike pricematrix(1:size(Olist,1),:)];

%varargin
ETF = pricematrix(size(pricematrix,1)-1,3)*1000;
% INDEX = pricematrix(size(pricematrix,1),3);
% TrackError1 = INDEX - ETF;
CURMON = Pricematrix(Pricematrix(:,2) == CurrentMonth,:);

Pricematrix00 = [Contract SDate Strike pricematrix00(1:size(Olist,1),:)];
CURMON00 = Pricematrix00(Pricematrix00(:,2) == CurrentMonth,:);


len = size(CURMON,1);
lenDiv2 = len/2;

buyOption00 = CURMON00(lenDiv2+1:end,:);
buyOption10 = CURMON00(1:lenDiv2, :);
sellOption00 = CURMON00(1:lenDiv2, :);
sellOption10 = CURMON00(lenDiv2+1:end,:);


optionPairs = [];


%dvnow = datevec(now);   

%load holding (version3 update)



sizeRawHolding = size(rawHolding,1);
LineNeedClean1 = zeros(sizeRawHolding,1);
countForLineNeedClean1 = 1;

for rh = 1:sizeRawHolding
    if  rawHolding(rh,3) == 0
        LineNeedClean1(countForLineNeedClean1,1) = rh;
        countForLineNeedClean1 = countForLineNeedClean1 + 1;
    else
    for rhc = 1:rh-1
        if rawHolding(rhc,2) == rawHolding(rh,2)
            if rawHolding(rhc,3) > rawHolding(rh,3)
                rawHolding(rh,3) = rawHolding(rhc,3) - rawHolding(rh,3);
                rawHolding(rh,1) = rawHolding(rhc,1);
                rawHolding(rhc,3) = 0;
            else if rawHolding(rhc,3) < rawHolding(rh,3)
                    rawHolding(rh,3) = rawHolding(rh,3) - rawHolding(rhc,3);
                    rawHolding(rhc,3) = 0;
                else
                    rawHolding(rhc,3) = 0;
                    rawHolding(rh,3) = 0;
                    LineNeedClean1(countForLineNeedClean1,1) = rh;
                    countForLineNeedClean1 = countForLineNeedClean1 + 1;
                end
            end
        LineNeedClean1(countForLineNeedClean1,1) = rhc;
        countForLineNeedClean1 = countForLineNeedClean1 + 1;
        end
    end
    end
end
LineNeedClean1(LineNeedClean1==0)=[];
rawHolding(LineNeedClean1,:) = [];


Holding = []; 
if sizeRawHolding ~= 0
    Holding(:,4) = rawHolding(:,1);
    Holding(:,7) = rawHolding(:,2);
    Holding(:,11) = rawHolding(:,3);
end

% Holding = csvread ('position.csv',1,0);

CHoldingcost = zeros(lenDiv2,3);
PHoldingcost = zeros(lenDiv2,3);
sizeHolding = size(Holding,1);

for i = 1:lenDiv2
    CHoldingcost(i,1) = CURMON(i,1);
    for l = 1:sizeHolding
        if CHoldingcost(i,1) == Holding(l,7)
            CHoldingcost(i,2) = Holding(l,4);
            CHoldingcost(i,3) = Holding(l,11);
        end
    end
end

for i = 1:lenDiv2
    PHoldingcost(i,1) = CURMON(i+lenDiv2,1);
    for l = 1:sizeHolding
        if PHoldingcost(i,1) == Holding(l,7)
            PHoldingcost(i,2) = Holding(l,4);
            PHoldingcost(i,3) = Holding(l,11);
        end
    end
end

%close out
for i=1:lenDiv2
    if CHoldingcost(i,3) ==0
        CHoldingcost(i,2) = 1;
        CHoldingcost(i,3) = Limitcost;
    end
     if PHoldingcost(i,3) ==0
        PHoldingcost(i,2) = 1;
        PHoldingcost(i,3) = Limitcost;
     end
end

%liquidcost
% CLiqcost = zeros(lenDiv2,4);
% PLiqcost = zeros(lenDiv2,4);
CLiqcost = CURMON(1:lenDiv2,[1 8 9 5]);
PLiqcost = CURMON(lenDiv2+1:end,[1 8 9 5]);
Liqcost = 1-log(CLiqcost(:,2)+10*CLiqcost(:,3))/log(max(CLiqcost(:,2)+10*CLiqcost(:,3))) + 1-log(PLiqcost(:,2)+10*PLiqcost(:,3))/log(max(PLiqcost(:,2)+10*PLiqcost(:,3))) ;

% %%error check
if mod(sum(CHoldingcost(CHoldingcost(:,2)==0,3)),50000)~=mod(sum(CHoldingcost(CHoldingcost(:,2)~=0,3)),50000)
    OrderlistR = [1,0,0,0,0]';
    disp('call holding does not match')
return;
end
    
if mod(sum(PHoldingcost(PHoldingcost(:,2)==0,3)),50000)~=mod(sum(PHoldingcost(PHoldingcost(:,2)~=0,3)),50000)
    OrderlistR = [1,0,0,0,0]';
    disp('put holding does not match')
return;
end

if rem(sum(rawHolding(:,3)),2)~=0
    OrderlistR = [1,0,0,0,0]';
    disp('rawholding does not match')
return;
end



% OPosition = [];

daysToSettlement = thirdwednesday(SDate(1)-floor(SDate(1)/100)*100,SDate(1)/100)+7-today;
% 
% 
% if thirdwednesday(dvnow(2), dvnow(1))+7-today >0
%     daysToSettlement = thirdwednesday(dvnow(2), dvnow(1))+7-today;
% else
%     t = 0;
%     if dvnow(2)+1 > 12 %如果跨年12月->明年一月
%         t = 1;
%     end
%     daysToSettlement = thirdwednesday(mod(dvnow(2)+1,12), dvnow(1) + t )+7-today;
% end

% DisPV = CURMON(:,3)*10000/exp(interestRate*daysToSettlement/365);
%%%

sellOption = CURMON(1:lenDiv2, :);        %call
buyOption = CURMON(lenDiv2+1:end,:);      %put


for i = 1:lenDiv2
    b = buyOption(i,:);         %put
    s = sellOption(i,:);        %call
    
    bData = b(end-19:end);      %put
    sData = s(end-19:end);      %call
    
    sellprice = sData(5:-1:1);      %call
    sellamount = sData(15:-1:11);   %call
    
    buyprice = bData(6:10);          %put
    buyamount = bData(16:20);       %put
    
    optionPairs = [optionPairs, OptionPair1a(b(1), sellprice, sellamount, buyprice, buyamount,daysToSettlement , b(3), interestRate,cap)];
end


lowPrice = [];
lengthOptionPairs = length(optionPairs);
for i = 1:lengthOptionPairs
    y = optionPairs(i).GetBestPriceNoneZero();
    lowPrice = [lowPrice,y];
end


prepareAmount = 0;
preparePair = [];
meetRequire = 1;
while( prepareAmount < desirMount )

    %holdingcost added
adjprice = [lowPrice.price] + Holdingcostmark * (PHoldingcost(:,2).*PHoldingcost(:,3))' + Liquidcostmark * Liqcost'+ ((-1)*(CLiqcost(:,4)+PLiqcost(:,4))+2)'*500000;
    [~, ind] = sort(adjprice);
    prepareAmount = prepareAmount+lowPrice(ind(1)).amount;
    if(lowPrice(ind(1)).price == inf)
        meetRequire = 0;
        break;
    end
    preparePair = [preparePair, lowPrice(ind(1))];% 
    lowPrice(ind(1)) = optionPairs(ind(1)).GetBestPriceNoneZero();
end

if(meetRequire == 0)
    OrderlistR = [0,0,0,0,0]';
    return;
end


preparePair(end).amount = preparePair(end).amount-(prepareAmount-desirMount);
% 
% for i=1:length(preparePair)
% preparePair = preparePair(preparePair.amount ~= 0);
% end

BCSPind = ind(1);

%%

buyOption1 = CURMON(1:lenDiv2, :);
sellOption1 = CURMON(lenDiv2+1:end,:);

optionPairs1 = [];

for i = 1:lenDiv2
    b1 = buyOption1(i,:);
    s1 = sellOption1(i,:);
    
    bData1 = b1(end-19:end);
    sData1 = s1(end-19:end);
    
    sellprice1 = sData1(5:-1:1);
    sellamount1 = sData1(15:-1:11);
    
    buyprice1 = bData1(6:10);
    buyamount1 = bData1(16:20);
    
    optionPairs1 = [optionPairs1, OptionPair2a(b1(1), sellprice1, sellamount1, buyprice1, buyamount1,daysToSettlement , b1(3), interestRate,cap)];
end


lowPrice1 = [];
lengthOptionPairs1 = length(optionPairs1);
for i = 1:lengthOptionPairs1
    y = optionPairs1(i).GetBestPriceNoneZero();
    lowPrice1 = [lowPrice1,y];
end

prepareAmount1 = 0;
preparePair1 = [];
meetRequire = 1;
while( prepareAmount1 < desirMount )
    
    %holdingcost added
    adjprice1 = [lowPrice1.price] + Holdingcostmark * (CHoldingcost(:,2).*CHoldingcost(:,3))'+ Liquidcostmark * Liqcost'+ ((-1)*(CLiqcost(:,4)+PLiqcost(:,4))+2)'*500000;
                [~, ind] = sort(adjprice1);
    prepareAmount1 = prepareAmount1+lowPrice1(ind(1)).amount;
    if(lowPrice1(ind(1)).price == inf)
        meetRequire = 0;
        break;
    end
    preparePair1 = [preparePair1, lowPrice1(ind(1))];
    lowPrice1(ind(1)) = optionPairs1(ind(1)).GetBestPriceNoneZero();
end

if(meetRequire == 0)
    OrderlistR = [0,0,0,0,0]';
    return;
end


preparePair1(end).amount = preparePair1(end).amount-(prepareAmount1-desirMount);

% for i=1:length(preparePair1)
% preparePair1 = preparePair1(preparePair1.amount ~= 0);
% end

BPSCind = ind(1);
%%



%*** need updating with holding file
Porderlist =[];
Porderlist(:,1) = preparePair.name;
% Porderlist(:,1) = statarray(:,1);
Porderlist(:,2) = 1;
Porderlist(:,3) = 2;
Porderlist(:,4) = 1;
% Porderlist(:,4) = sumamount(:,1);
Porderlist(:,5) = buyOption(BCSPind,15);

for i = 1:lenDiv2
    if CURMON(lenDiv2+i,4) == Porderlist(:,1)
        cid = i;
        break;
    end
end

Corderlist =[];
Corderlist(:,1) = CURMON(cid,4);
% Corderlist(:,1) = Matchpair(:,4);
Corderlist(:,2) = 1;
Corderlist(:,3) = 1;
Corderlist(:,4) = 1;
% Corderlist(:,4) = sumamount(:,1);
Corderlist(:,5) = sellOption(BCSPind,14);


Orderlist1 = [Corderlist;Porderlist];

%statistic

totcost = [preparePair.price]*[preparePair.amount]';
% avgcost = [preparePair.price]*[preparePair.amount]'/sum([preparePair.amount]);
% Optionpandd = (ETF)*desirMount*10 - totcost;

%save data
%saveOptionpandl = [saveOptionpandl;Optionpandd];


 
%----------------------------------------------

                                                                            %

%*** need updating with holding file
Corderlist1 =[];
Corderlist1(:,1) = preparePair1.name;
% Corderlist1(:,1) = statarray1(:,1);
Corderlist1(:,2) = 1;
Corderlist1(:,3) = 2;
Corderlist1(:,4) = 1;
% Corderlist1(:,4) = sumamount1(:,1);
Corderlist1(:,5) = buyOption1(BPSCind,15);

for i = 1:lenDiv2
    if CURMON(i,4) == Corderlist1(:,1)
        pid = i;
        break;
    end
end

Porderlist1 =[];
Porderlist1(:,1) = CURMON(pid+lenDiv2,4);
% Porderlist1(:,1) = Matchpair1(:,4);
Porderlist1(:,2) = 1;
Porderlist1(:,3) = 1;
Porderlist1(:,4) = 1;
% Porderlist1(:,4) = sumamount1(:,1);
Porderlist1(:,5) = sellOption1(BPSCind,14);


ReOrderlist1 = [Corderlist1;Porderlist1];

%statistic

totcost1 = [preparePair1.price]*[preparePair1.amount]';
% avgcost1 = [preparePair1.price]*[preparePair1.amount]'/sum([preparePair1.amount]);
% Optionpandd1 =  (ETF)*desirMount*10 + totcost1;
%
% j;
Boxprofit = -totcost1 - totcost;

% %save data
% saveOptionpandl1 = [saveOptionpandl1;Optionpandd1];
% 
% SaveBoxprofit = [SaveBoxprofit Boxprofit];
% 
% SaveCURMON = [SaveCURMON;CURMON];

Orderlist = [Orderlist1;ReOrderlist1];

%%
if Boxprofit >= actionpoint

%update open/close
sizeOrderlist = size(Orderlist,1);
for k = 1:sizeOrderlist
    for l = 1:sizeHolding
        if Orderlist(k,1) == Holding(l,7)
            if (Orderlist(k,3) -1.5) * (Holding(l,4) -0.5) == 0.25
                Orderlist(k,2) = 1;
            else if (Orderlist(k,3) -1.5) * (Holding(l,4) -0.5) == -0.25
                Orderlist(k,2) = 2;
                end
            end
        end
    end
end

lineNeedClean = zeros(sizeOrderlist,1);
for k = 1:sizeOrderlist
    if Orderlist(k,4) == 0
        lineNeedClean(k,1) = k;
    end
end
lineNeedClean(lineNeedClean==0) = [];
Orderlist(lineNeedClean, :) = [];

% %short open only
for kk = 1:sizeOrderlist
    if Orderlist(kk,3) == 2
        Orderlist(kk,2) = 1;
    end
end



%price change

buyOptionchange = buyOption - buyOption00;
buyOption1change = buyOption1 - buyOption10;
sellOptionchange = sellOption - sellOption00;
sellOption1change = sellOption1 - sellOption10;




% %multiple contract/order
% orderconstraint = floor(Boxprofit/actionpoint);
% orderlimit = [orderconstraint 5 sellOption(BCSPind,24) buyOption(BCSPind,25) buyOption1(BPSCind,25) sellOption1(BPSCind,24)]; 
% orderamount = min(orderlimit,[],2);
% Orderlist(:,4) = orderamount;

%adjust order for order
Orderlag = [sellOption(BCSPind,7) sellOption(BCSPind,24) -sellOptionchange(BCSPind,14);buyOption(BCSPind,7) buyOption(BCSPind,25) buyOptionchange(BCSPind,15);buyOption1(BPSCind,7) buyOption1(BPSCind,25) buyOption1change(BPSCind,15);sellOption1(BPSCind,7) sellOption1(BPSCind,24) -sellOption1change(BPSCind,14)];

Orderlistlag1 = [Orderlist Orderlag];
[~, lagind1] = sort(Orderlistlag1(:,7));
Orderlistlag2 = [Orderlistlag1(lagind1(1),:);Orderlistlag1(lagind1(2),:);Orderlistlag1(lagind1(3),:);Orderlistlag1(lagind1(4),:)];
[~, lagind2] = sort(Orderlistlag2(:,6));
Orderlistlag3 = [Orderlistlag2(lagind2(1),:);Orderlistlag2(lagind2(2),:);Orderlistlag2(lagind2(3),:);Orderlistlag2(lagind2(4),:)];
[~, lagind3] = sort(Orderlistlag3(:,8));
Orderlistlag = [Orderlistlag3(lagind3(4),:);Orderlistlag3(lagind3(3),:);Orderlistlag3(lagind3(2),:);Orderlistlag3(lagind3(1),:)];
OrderlistR = Orderlistlag(:,1:5);

%output mkt/lmt order

if  Orderlistlag3(lagind3(4),8) < limitordermark/10000
    OrderlistR(:,5) = 0;
end
    


%output csv file
% dlmwrite('order.csv',Orderlist,'precision',15);
% % Futureorder1 = ('IH1511, 1, 1, 1');
% fid1=fopen('order.csv','at');
% fprintf(fid1,Futureorder1);
% fclose(fid1);

% % %Backtest position file update
% lineNeedDel = [];
% extraHolding = [];
% for k = 1:size(Orderlist,1)
%     isExisted = 0;
%     for l = 1:size(Holding,1)
%              if Orderlist(k,1) == Holding(l,7)
%             isExisted = 1;
% 
%                 if (Orderlist(k,3) -1.5) * (Holding(l,4) -0.5) == 0.25
%                Holding(l,11) = Holding(l,11) + 1;
%                 else if (Orderlist(k,3) -1.5) * (Holding(l,4) -0.5) == -0.25
%                Holding(l,11) = Holding(l,11) - 1;
%                         if Holding(l,11) == 0
%                             lineNeedDel = [lineNeedDel; l];
%                         end
%                 end
%                 end 
%         
%             
%          end
%     end
%     
%     if(isExisted == 0)
%         eh = zeros(1,11);
%         eh(7) = Orderlist(k,1);
%         if Orderlist(k, 3) == 1
%             eh(4) = 0;
%             eh(11) =1;
%         end
%         if Orderlist(k, 3) == 2
%             eh(4) = 1;
%             eh(11) =1;
%         end
%         extraHolding = [extraHolding; eh];
%     end
% end
% Holding(lineNeedDel, :) = [];
% 
% Holding = [zeros(1,11);Holding;extraHolding];
% 
% dlmwrite('position.csv',Holding,'precision',15);

% 
% % %Trade
% system('ufx.exe order.csv');


% OrderTrack = [OrderTrack;zeros(1,4);Orderlist];

%track (one trade only)
newTraderecord  = [rem(now,1) Boxprofit Corderlist(1,1) sellOption(BCSPind,14) Porderlist(1,1) buyOption(BCSPind,15)  Corderlist1(1,1) buyOption1(BPSCind,15)  Porderlist1(1,1) sellOption1(BPSCind,14) sellOption(BCSPind,24) buyOption(BCSPind,25) buyOption1(BPSCind,25) sellOption1(BPSCind,24) sellOption(BCSPind,7) buyOption(BCSPind,7) buyOption1(BPSCind,7) sellOption1(BPSCind,7) OrderlistR(1,1) Orderlistlag(1,8) OrderlistR(2,1) Orderlistlag(2,8) OrderlistR(3,1) Orderlistlag(3,8) OrderlistR(4,1) Orderlistlag(4,8)]; 
newTraderecord = newTraderecord';

OrderlistR = OrderlistR';

% %%preparePair1.price preparePair1.amount preparePair.price preparePair.amount
% 
% Traderecord = [Traderecord; newTraderecord];
% dlmwrite(strcat(ufxPath,'Traderecord.csv'),Traderecord,'precision',15);
% 
% HoldingTrack = [HoldingTrack;zeros(1,11);Holding];
%AllOrder = [AllOrder Orderlist];

% 
% plot(rem(now,1),Boxprofit, 'd-');
% hold all;
% pause(2)

else
    OrderlistR = [0,0,0,0,0]';
end

% 
%charting
% plot(rem(now,1),Optionpandd1, 'o-'); 
% hold all;
% 
% plot(rem(now,1),Optionpandd, '*-');
% hold all;

% 
% plot(rem(now,1),Boxprofit, 'd-');
% hold all;
end