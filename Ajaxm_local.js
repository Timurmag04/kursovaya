
//        getDataPicker('databeg');
//        getDataPicker('dataend');



          function showpochasclick(){
            window.open('pochasovka.php?uchgod='+document.getElementById('uchgodspan').innerHTML+'&dbeg='+document.getElementById('databeg').value+'&dend='+document.getElementById('dataend').value+'&kid='+document.getElementById('kidspan').value+'&vak='+document.getElementById('vakspan').value+'&kaf='+document.getElementById('kafspan').value,'_blank');
            };  
/*
function getDataPicker(id){
			$( "#"+id+"" ).datepicker({
									dayNamesMin: ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"],
									dayNames: ["Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота"],
									monthNames: ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"],
									firstDay: 1,
									dateFormat: "dd.mm.yy"
								});
}
*/


var openedWindow;

      // openedWindow = window.open('http://rcell.ru');
       //openedWindow.close();


var xmlHttp; 
        function createXMLHttpRequest() 
         { 
             if (window.ActiveXObject) 
             { 
                 xmlHttp = new ActiveXObject("Microsoft.XMLHTTP"); 
             } 
             else if (window.XMLHttpRequest) 
             { 
                 xmlHttp = new XMLHttpRequest(); 
             } 
         } 

        function startRequest(label,par1,par2) 
         { 
             createXMLHttpRequest(); 
             xmlHttp.onreadystatechange = handleStateChangeRASP; 
             xmlHttp.open("POST", "Ajaxm.php", true);
 	         xmlHttp.setRequestHeader("Content-Type", "application/x-www-form-urlencoded");
               document.body.style.cursor = "wait";
   	           if(null!=document.getElementById('blockdiv')){document.getElementById('blockdiv').style.height=document.body.scrollHeight+"px";}	
	           if(null!=document.getElementById('blockdiv')){document.getElementById('blockdiv').style.visibility="visible";}
			   
                  switch (label) {
                //Для выбора факультета после выброра филиала или выбора формы обучения
                    case '001' :
 					  var rfind=document.getElementById('rfind').value;
					  switch (rfind) 
						  {
                           case '1':							  
                             var postData = "p=001;filial="+document.getElementById('rfilial').value+";fob="+document.getElementById('rfob').value+";uchgod="+par1+";semestr="+par2+";" ;						   
                           break;									 							  
                           case '2':							  
                             var postData = "p=008"+document.getElementById('rfilial').value;						   
                           break;									 							  
						   
						  }
                       break;									 							  		
   //Для выбора специальности после выбора факультета
                    case '002' :
                     var postData = "p=002;filial="+document.getElementById('rfilial').value+";fob="+document.getElementById('rfob').value+";fak="+document.getElementById('rfakk').value+";uchgod="+par1+";semestr="+par2+";" ;
					 break;						  
                //Для выбора специальности после выбора факультета
                    case '003' :
                     var postData = "p=003;filial="+document.getElementById('rfilial').value+";fob="+document.getElementById('rfob').value+";fak="+document.getElementById('rfakk').value+";kurs="+document.getElementById('rkurs').value+";uchgod="+par1+";semestr="+par2+";" ;
					 break;									 
                //Ищет кадрid по запросу
                    case '004' :
                     var postData = "p=004;vval="+escape(par1)+";param="+par2+";sem="+document.getElementById('rsem').value+";";
					 break;									 
                //Ищет audid по запросу
                    case '005' :
                     var postData = "p=005;vval="+par1+";param="+par2+";sem="+document.getElementById('rsem').value+";fil="+document.getElementById('rfilial').value+";";
					 break;									 
                    case '006' :
                     var postData = "p=006;vval="+escape(par1)+";filial="+document.getElementById('rfilial').value+";";
					 break;									 
                //поиск свободной аудитории
                    case '007' :
                     var postData = "p=007;korp="+document.getElementById('allkorp').value+';para='+document.getElementById('allpara').value+';day='+document.                          getElementById('allday').value+';begweek='+document.getElementById('begned').value+';endweek='+document.getElementById('endned').value+';countseets='+countsets+';';
					 break;									 
					 
					 
                   case '010' :
					 var postData = "p=010"+par1;
					break;
                   case '011' :
					 var postData = "p=011;data="+par1+';';
					break;
                   case '012' :
					 var postData = "p=012;gruppa="+par1+';semestr='+par2+';filial='+document.getElementById('rfilial').value+';';
					break;
					
                   case '013' :
					var postData = "p=013;data="+par1+';';
					break;



                    case '016' :
                     var postData = "p=016"+par1;
					 break;
					 
                    case '017' :
                     var postData = "p=017"+par1;
					 break;
					 
                     } 
					 
            xmlHttp.send(postData);
         }

        function handleStateChangeRASP() 
         { 
             if(xmlHttp.readyState == 4) 
             { 
                 if(xmlHttp.status == 200) 
                 { 
                 var qw = unescape(xmlHttp.responseText);
		 qw = qw.substring(qw.indexOf('start')+5);
                      Rezaltall(qw); 
                 }else{ 
              window.alert('Что-то не то');
                  } 

             }
         } 

        function Rezaltall(ttext) 
         { 
         var llabel = ttext.substring(0,3) + '';  
             ttext = ttext.substr(3,ttext.length-3);
               if(null!=document.getElementById('blockdiv')){document.getElementById('blockdiv').style.visibility="hidden";}
			   document.body.style.cursor = "default";
                  switch (llabel) {
         			  case '001' :
              document.getElementById('rfakktd').innerHTML=ttext;
					  break; 
                    case '002' :
              document.getElementById('rkurstd').innerHTML=ttext;
					  break;	
                    case '003' :
              document.getElementById('rgrupptd').innerHTML=ttext;
					  break;	
                    case '004' :
					var vall = ttext.split(';');
					 if (vall[1]==1)
					   { document.body.style.cursor = "wait";
						   window.open('index.php?kid='+(vall[0])+'&family='+escape(vall[2])+'&sem='+document.getElementById('rsem').value,'_self');}
					   else
					   {document.getElementById('findrezult').innerHTML=vall[0];}
					  break;	
                    case '005' :
					var vall = ttext.split(';');
					 if (vall[1]==1)
					   {document.body.style.cursor = "wait";
						   window.open('index.php?aud='+(vall[0])+'&family='+encodeURIComponent(vall[2])+'&sem='+document.getElementById('rsem').value,'_self')}
					   else
					   {document.getElementById('findrezult').innerHTML=vall[0];}
					  break;	
                    case '006' :
					   document.getElementById('kadrr').innerHTML=ttext;
					  break;	
                    case '007' :
					   document.getElementById('rezulttd').innerHTML=ttext;
					  break;	
                    case '008' :
					   document.getElementById('slov_kafedr').innerHTML=ttext;
					  break;	
					  
                    case '010' :
					window.alert('Дисциплина удалена!');						 
					window.close();
					  break;	
                    case '011' :
					document.getElementById('begned').value=ttext;						 
					  break;	
                    case '012' :
					document.getElementById('fgh').innerHTML=ttext;						 
					  break;	
					  
                    case '013' :
					document.getElementById('endned').value=ttext;
					  break;	
                    case '016' :
					var vall=ttext.split('@');
					document.getElementById('ndiscdiv').innerHTML=vall[0];
					var arr=vall[1].split(';');  
                      for (ii=0;ii<arr.length-1;ii++)
					     {
						   discarray[ii]=arr[ii];  
						 }
					nomactivediscarr=-1;
					countfinddisc=arr.length-2;
					  break;	
					case '017' :
					window.alert(ttext);
			        window.close();
					break;
					  
                    }

          }

//Задает стартовые позиции
function startparam(vv)
{
	document.getElementById('rfind').value=vv;
	findfor(vv);
	//window.alert(vv);
}



function testgruppa(vval)
 {
	 if(vval!=0){
		 document.body.style.cursor = "wait";
		 window.open("index.php?filial="+document.getElementById('rfilial').value+"&fob="+document.getElementById('rfob').value+"&fak="+document.getElementById('rfakk').value+"&kurs="+document.getElementById('rkurs').value+"&gruppa="+escape(vval)+'&sem='+document.getElementById('rsem').value,'_self');
	 }

 }
 
 function TogglePost() {
	 post=document.getElementById('peramtable')
      if (post.style.visibility == "hidden") {
      // Show the post
      post.style.visibility = "visible";
      post.style.position = "relative";
      post.style.top = "0";
      post.style.left = "0";

    } else {
      // Hide the post
      post.style.visibility = "hidden";
      post.style.position = "absolute";
      post.style.top = "-10000";
      post.style.left = "-10000";
    }
  }
 
function findfor(vval)
 {
  switch (vval) {
   case '2' ://prepod
    //document.getElementById('rfilial').disabled=true;
    document.getElementById('rfob').disabled=true;
    document.getElementById('rfakk').disabled=true;	
    document.getElementById('rkurs').disabled=true;	
    document.getElementById('rgrupp').disabled=true;
	document.getElementById('fiolabel').disabled=false;
	document.getElementById('rfio').disabled=false;	
	document.getElementById('rfindbtn').disabled=true;	
	document.getElementById('audlabel').disabled=true;
	document.getElementById('raud').disabled=true;	
	//document.getElementById('rfindbtn').setAttribute("onclick", function() {findbtnfunc('2');});
	if (null!=document.getElementById('kadrvak')){document.getElementById('kadrvak').disabled=false;} 	
break; 
   case '3' :
//    document.getElementById('rfilial').disabled=true;
    document.getElementById('rfob').disabled=true;
    document.getElementById('rfakk').disabled=true;	
    document.getElementById('rkurs').disabled=true;	
    document.getElementById('rgrupp').disabled=true;
	document.getElementById('audlabel').disabled=false;
	document.getElementById('raud').disabled=false;	
	document.getElementById('rfindbtn').disabled=false;	
	document.getElementById('raud').value="";	
	document.getElementById('rfio').disabled=true;	
	document.getElementById('fiolabel').disabled=true;
	//document.getElementById('rfindbtn').setAttribute("onclick", function() {findbtnfunc('3');});
		if (null!=document.getElementById('kadrvak')){document.getElementById('kadrvak').disabled=true;} 
	
break; 

default:
    document.getElementById('rfilial').disabled=false;
    document.getElementById('rfob').disabled=false;
    document.getElementById('rfakk').disabled=false;	
    document.getElementById('rkurs').disabled=false;	
    document.getElementById('rgrupp').disabled=false;
	document.getElementById('fiolabel').disabled=true;
	document.getElementById('rfio').disabled=true;	
	document.getElementById('rfindbtn').disabled=true;	
	document.getElementById('audlabel').disabled=true;
	document.getElementById('raud').disabled=true;	
	if (null!=document.getElementById('kadrvak')){document.getElementById('kadrvak').disabled=true;} 

  break;
  }
 }

function findbtnfunc()
{

	param=document.getElementById('rfind').value;

	  switch (param) {
   case '2' :
    if (vval=="")
	  { window.alert('введите Фамилию');}else{startRequest('004',vval,param);}
	 break;
   case '3' :
   	vval=document.getElementById('raud').value;
    if( /.{1,}-{1}/i.test(vval)==false){window.alert('Данные введены не по формату')}else{startRequest('005',vval,param);}
    break;
                    }
}

function setprepod(vaval)
 {
	 if (vaval!='0')
	 {
	  startRequest('006',vaval,'');
	 }
 }

function showbegunokprep(vval, ffilial)
 {
    sem=document.getElementById('rsem').value;
	selIndex = document.getElementById('kadrvak').selectedIndex;
	family=document.getElementById('kadrvak').options[selIndex].text;
	kafedra=document.getElementById('rfio').options[document.getElementById('rfio').selectedIndex].text
	kaf=document.getElementById('rfio').value;
   var pp=vval.split('@');
      if (pp[0]=='0') //это не вакансия
	   {
         window.open(encodeURI('index.php?kid='+pp[1]+'&vak=0&family='+family+'&kaf='+kaf+'&kafedra='+kafedra+'&sem='+sem+'&filial='+ffilial),'_self');
       }else{
         window.open(encodeURI('index.php?kid=0&vak='+pp[1]+'&family='+family+'&kaf='+kaf+'&kafedra='+kafedra+'&sem='+sem+'&filial='+ffilial),'_self');
	   }
  }
